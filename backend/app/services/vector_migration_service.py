"""Explicit offline copying of reachable immutable builds, with verifiable rollback."""

from __future__ import annotations

import math
import re
from contextlib import asynccontextmanager
from types import SimpleNamespace

from app.core.db import execute, fetch_all, fetch_one, require_pool
from app.core.values import load
from app.rag.artifact_store import ArtifactStore
from app.rag.contracts import BuildResult, stable_hash
from app.rag.errors import SourceUnavailable
from app.rag.index_artifacts import (
    _digest_for, deep_artifact_checks, embedding_space_signature, read_manifest,
    ref_from_manifest, run_file_io,
)
from app.rag.vector_archive import load_source_vectors, iter_source_vectors, save_source_vectors
from app.services import vector_projection_service as registry


async def inventory(store: ArtifactStore):
    """Every published historical build, not only the current active build."""
    rows = await fetch_all(
        "SELECT b.manifest_json,b.published_attempt_id,d.authorization_revision,b.build_id,b.doc_id,b.owner_id,b.version_id,b.namespace,b.index_profile_hash,b.created_at,d.namespace AS source_namespace "
        "FROM kb_index_builds b JOIN kb_documents d ON d.doc_id=b.doc_id AND d.user_id=b.owner_id "
        "WHERE (b.status='ready' OR b.published_attempt_id IS NOT NULL OR b.build_id=d.active_build_id) AND d.deleted_at IS NULL"
    )
    # MySQL filesort can copy large JSON manifests into its bounded sort buffer.
    # Sort the already-loaded row references without sorting JSON in the database.
    rows = sorted(rows, key=lambda row: (row["owner_id"], row["doc_id"], str(row["created_at"] or ""), row["build_id"]))
    builds = []
    for row in rows:
        def checked(row=row):
            built = BuildResult.model_validate(load(row["manifest_json"]))
            identity = {"attempt_id": "published_attempt_id", "index_build_id": "build_id", "doc_id": "doc_id", "owner_id": "owner_id", "document_version_id": "version_id", "namespace": "namespace", "index_profile_hash": "index_profile_hash"}
            if any(getattr(built, field) != row[column] for field, column in identity.items()) or built.namespace != row["source_namespace"]:
                raise SourceUnavailable("SQL published identity differs from its manifest")
            if built.embedding_dimensions != built.profile.embedding_dimensions or built.index_profile_hash != built.profile.profile_hash:
                raise SourceUnavailable("Published embedding space differs from its frozen profile")
            restored = read_manifest(store, built.to_source_manifest(row["authorization_revision"]))
            if restored != built:
                raise SourceUnavailable("SQL and immutable build artifacts differ")
            return built
        builds.append(await run_file_io(checked))
    return builds


def ref_for(built, backend, revision, prefix):
    return ref_from_manifest(
        built.to_source_manifest(1), backend=backend, target_revision=revision,
        embedding_signature_hash=embedding_space_signature(built.profile), collection_prefix=prefix,
    )


def archive_rows(store, archive):
    return [row for batch in iter_source_vectors(store, archive) for row in batch]


@asynccontextmanager
async def maintenance(*, recovery_proof=None, projection=None):
    """Use only after API writes and vector workers have been stopped/drained."""
    async with require_pool().acquire() as conn:
        lock_name = registry.maintenance_lock_name()
        lock = await fetch_one("SELECT GET_LOCK(%s,0) AS acquired", (lock_name,), conn=conn)
        if lock["acquired"] != 1:
            raise SourceUnavailable("Another vector maintenance command is running")
        try:
            with registry.maintenance_context():
                if recovery_proof is not None:
                    uncertain = await fetch_one("SELECT operation_id FROM rag_vector_operations WHERE backend='qdrant' AND status<>'finished' AND recovery_json IS NULL LIMIT 1", conn=conn)
                    if uncertain and projection is None:
                        raise SourceUnavailable("Qdrant restart evidence is required for recovery")
                    startup = await projection.server_startup() if uncertain else None
                    await registry.recover_after_exit(recovery_proof, qdrant_startup=startup)
                workers = await fetch_all(
                    "SELECT role FROM worker_heartbeats WHERE role IN ('rag_owner','rag_writer','rag_generation') AND heartbeat_at>UTC_TIMESTAMP(6)-INTERVAL 90 SECOND", conn=conn,
                )
                running = await fetch_one(
                    "SELECT t.task_id FROM quiz_tasks t WHERE t.status='running' AND NOT EXISTS ("
                    "SELECT 1 FROM rag_execution_receipts r WHERE r.task_id=t.task_id AND r.attempt=t.attempt AND r.worker_id=t.worker_id AND r.recovery_json IS NOT NULL) LIMIT 1", conn=conn,
                )
                receipts = await fetch_one("SELECT receipt_id FROM rag_execution_receipts WHERE status<>'finished' AND recovery_json IS NULL LIMIT 1", conn=conn)
                pending = await fetch_one("SELECT operation_id FROM rag_vector_operations WHERE status<>'finished' AND recovery_json IS NULL LIMIT 1", conn=conn)
                if workers or running or receipts or pending:
                    raise SourceUnavailable("Drain all executors and recover unconfirmed operations before maintenance")
                yield
        finally:
            try:
                await execute("SELECT RELEASE_LOCK(%s)", (lock_name,), conn=conn)
            except BaseException:
                conn.close()
                raise


async def plan(store, *, revision, prefix):
    builds = await inventory(store)
    return {
        "status": "planned", "projection_count": len(builds),
        "vector_count": sum(b.node_count for b in builds),
        "projections": [
            {"projection_key": b.projection_key, "doc_id": b.doc_id, "owner_id": b.owner_id,
             "node_count": b.node_count, "dimensions": b.embedding_dimensions,
             "collection": ref_for(b, "qdrant", revision, prefix).collection_name}
            for b in builds
        ],
    }


async def _adopt_legacy_attempts(chroma, builds, run_id):
    """Failed unpublished attempts remain owned and discoverable for deletion."""
    published = {b.projection_key for b in builds}
    docs = await fetch_all("SELECT doc_id,user_id,namespace FROM kb_documents")
    adopted = 0
    for doc in docs:
        intents = await run_file_io(lambda: chroma.attempts_for_document(owner_id=doc["user_id"], namespace=doc["namespace"], doc_id=doc["doc_id"]))
        for intent in intents:
            if intent["projection_key"] in published:
                continue
            registered = await fetch_one("SELECT projection_key FROM rag_vector_projections WHERE projection_key=%s AND backend='chroma' AND target_revision='legacy-v1'", (intent["projection_key"],))
            if registered:
                continue
            ref = ref_from_manifest(SimpleNamespace(**{**intent, "index_profile_hash": intent.get("index_profile_hash", "")}))
            prior = await registry.register_candidate(ref, migration_run_id=run_id, allow_revoked=True)
            if prior is None:
                await execute(
                    "UPDATE rag_vector_projections SET status='failed' WHERE projection_key=%s AND backend='chroma' AND target_revision='legacy-v1'",
                    (ref.projection_key,),
                )
                adopted += 1
    return adopted


async def _source_archive(chroma, built, run_id):
    ref = ref_for(built, "chroma", "legacy-v1", "xunke_dense")
    await registry.register_candidate(ref, migration_run_id=run_id)
    await run_file_io(deep_artifact_checks, chroma, built)
    key = built.projection_key + "/source-vectors.json"
    if chroma.resolve_key(key).exists():
        archive = load_source_vectors(chroma, key)
        rows = await run_file_io(archive_rows, chroma, archive)
    else:
        rows = [row async for row in chroma.projection.iter_vectors(ref)]
        archive = await run_file_io(save_source_vectors, chroma, ref, rows)
    expected = _digest_for(built.node_count, built.embedding_dimensions, [n.node_id for n in built.nodes if not n.is_parent], archive)
    if archive.node_set_hash != expected.node_set_hash or archive.count != built.node_count:
        raise SourceUnavailable("Source archive does not cover the published node set")
    await registry.attach_archive(ref, archive, expected)
    verified = await chroma.projection.verify_attempt(ref, expected, archive, source_rows=rows)
    await registry.record_verified(ref, verified, publish_physical=True)
    return archive, rows, expected


async def _copy_batches(projection, ref, rows):
    actual = {row.node_id: row.vector async for row in projection.iter_vectors(ref)}

    def batch_matches(batch):
        for row in batch:
            vector = actual.get(row.node_id)
            norm = math.sqrt(math.fsum(value * value for value in row.vector))
            if vector is None or len(vector) != len(row.vector) or not norm:
                return False
            if any(abs(value - original / norm) > 1e-6 + 1e-5 * abs(original / norm) for value, original in zip(vector, row.vector)):
                return False
        return True

    for batch in projection.iter_write_batches(ref, rows):
        batch_hash = stable_hash([r.model_dump(mode="json") for r in batch])
        prior = await fetch_one(
            "SELECT operation_id FROM rag_vector_operations WHERE projection_key=%s AND backend=%s AND target_revision=%s AND operation_kind='write' AND batch_hash=%s AND status='finished' LIMIT 1",
            (ref.projection_key, ref.backend, ref.target_revision, batch_hash),
        )
        if prior and batch_matches(batch):
            continue
        await registry.recorded_call(ref, "write", lambda: projection.write_attempt(ref, batch), rows=batch)


async def copy(chroma, remote, *, run_id):
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", run_id):
        raise ValueError("Invalid vector migration run id")
    builds = await inventory(chroma)
    report = {"status": "copying", "run_id": run_id, "source_backend": "chroma", "target_backend": "qdrant", "target_revision": remote.target_revision, "collection_prefix": remote.collection_prefix, "projections": []}
    report_key = f"rag/vector-migrations/{run_id}.json"
    if remote.resolve_key(report_key).exists():
        prior_report = await run_file_io(lambda: load(remote.resolve_key(report_key).read_text(encoding="utf-8")))
        if any(prior_report.get(key) != report[key] for key in ("source_backend", "target_backend", "target_revision", "collection_prefix")):
            raise SourceUnavailable("Migration run id already belongs to a different source or target")
    for built in builds:
        archive, rows, expected = await _source_archive(chroma, built, run_id)
        ref = ref_for(built, "qdrant", remote.target_revision, remote.collection_prefix)
        prior = await registry.register_candidate(ref, migration_run_id=run_id)
        await registry.attach_archive(ref, archive, expected)
        await remote.projection.initialize_collection(ref, built.embedding_dimensions)
        valid = False
        if prior and prior["status"] == "ready":
            try:
                await remote.projection.verify_attempt(ref, expected, archive, source_rows=rows)
                valid = True
            except SourceUnavailable:
                await registry.prepare_rewrite(ref)
        if not valid:
            await _copy_batches(remote.projection, ref, rows)
        verified = await remote.projection.verify_attempt(ref, expected, archive, source_rows=rows)
        await registry.record_verified(ref, verified, publish_physical=True)
        report["projections"].append({
            "projection_key": ref.projection_key, "count": archive.count,
            "source_vectors_hash": archive.source_vectors_hash,
            "target_vectors_hash": verified.digest.target_vectors_hash,
            "max_abs_error": verified.digest.max_abs_error,
        })
        await run_file_io(lambda: remote.put_json(report_key, report, immutable=False))
    report["adopted_failed_attempts"] = await _adopt_legacy_attempts(chroma, builds, run_id)
    report["status"] = "verified"
    await run_file_io(lambda: remote.put_json(report_key, report, immutable=False))
    return report


async def verify(store, projection, *, backend, revision, prefix):
    builds = await inventory(store)
    verified_items = []
    for built in builds:
        ref = await registry.require_ready(built, backend=backend, target_revision=revision)
        archive = await run_file_io(load_source_vectors, store, built.projection_key + "/source-vectors.json")
        rows = await run_file_io(archive_rows, store, archive)
        expected = _digest_for(built.node_count, built.embedding_dimensions, [n.node_id for n in built.nodes if not n.is_parent], archive)
        await run_file_io(deep_artifact_checks, store, built)
        checked = await projection.verify_attempt(ref, expected, archive, source_rows=rows)
        verified_items.append({"projection_key": ref.projection_key, "count": archive.count,
                               "max_abs_error": checked.digest.max_abs_error})
    return {"status": "verified", "backend": backend, "projection_count": len(builds), "projections": verified_items}


async def switch_check(store, *, backend, revision, projection=None):
    builds = await inventory(store)
    failures = []
    for built in builds:
        try:
            ref = await registry.require_ready(built, backend=backend, target_revision=revision)
            archive = await run_file_io(load_source_vectors, store, built.projection_key + "/source-vectors.json")
            rows = await run_file_io(archive_rows, store, archive)
            expected = _digest_for(built.node_count, built.embedding_dimensions, [n.node_id for n in built.nodes if not n.is_parent], archive)
            registered = await fetch_one("SELECT archive_json,expected_json,verified_json FROM rag_vector_projections WHERE projection_key=%s AND backend=%s AND target_revision=%s", (ref.projection_key, backend, revision))
            if (load(registered["archive_json"]) != archive.model_dump(mode="json")
                or any(load(registered["expected_json"]).get(field) != getattr(expected, field) for field in ("expected_node_count", "dimensions", "node_set_hash", "source_vectors_hash"))
                or load(registered["verified_json"])["digest"]["source_vectors_hash"] != archive.source_vectors_hash):
                raise SourceUnavailable("Readiness archive differs from its registered verification")
            await run_file_io(deep_artifact_checks, store, built)
            if projection is not None:
                await projection.verify_attempt(ref, expected, archive, source_rows=rows)
        except Exception:
            failures.append(built.projection_key)
    pending = await fetch_one("SELECT COUNT(*) AS count FROM rag_vector_operations WHERE status<>'finished' AND recovery_json IS NULL")
    deleting = await fetch_one("SELECT COUNT(*) AS count FROM rag_vector_projections WHERE status='deleting'")
    receipts = await fetch_one("SELECT COUNT(*) AS count FROM rag_execution_receipts WHERE status<>'finished' AND recovery_json IS NULL")
    workers = await fetch_one(
        "SELECT COUNT(*) AS count FROM worker_heartbeats WHERE role IN ('rag_owner','rag_writer','rag_generation') AND heartbeat_at>UTC_TIMESTAMP(6)-INTERVAL 90 SECOND"
    )
    report = {"status": "ready_to_switch", "backend": backend, "projection_count": len(builds),
              "missing_or_invalid": failures, "unconfirmed_operations": pending["count"],
              "pending_deletions": deleting["count"], "undrained_executions": receipts["count"], "active_workers": workers["count"]}
    if projection is not None and hasattr(projection, "healthcheck"):
        report["backend_available"] = await projection.healthcheck()
        if not report["backend_available"]:
            failures.append("backend_unavailable")
    if failures or any(report[k] for k in ("unconfirmed_operations", "pending_deletions", "undrained_executions", "active_workers")):
        report["status"] = "blocked"
    return report


async def restore_chroma(chroma, *, qdrant_revision, run_id):
    builds = await inventory(chroma)
    restored = []
    for built in builds:
        await run_file_io(deep_artifact_checks, chroma, built)
        archive = await run_file_io(load_source_vectors, chroma, built.projection_key + "/source-vectors.json")
        rows = await run_file_io(archive_rows, chroma, archive)
        ref = ref_for(built, "chroma", "legacy-v1", "xunke_dense")
        expected = _digest_for(built.node_count, built.embedding_dimensions, [n.node_id for n in built.nodes if not n.is_parent], archive)
        prior = await registry.register_candidate(ref, migration_run_id=run_id)
        await registry.attach_archive(ref, archive, expected)
        valid = False
        if prior and prior["status"] == "ready":
            try:
                await chroma.projection.verify_attempt(ref, expected, archive, source_rows=rows)
                valid = True
            except SourceUnavailable:
                await registry.prepare_rewrite(ref)
        if not valid:
            await registry.recorded_call(ref, "write", lambda: chroma.projection.write_attempt(ref, rows), rows=rows)
        checked = await chroma.projection.verify_attempt(ref, expected, archive, source_rows=rows)
        await registry.record_verified(ref, checked, publish_physical=True)
        restored.append(built.projection_key)
    return {"status": "restored", "projection_count": len(restored), "projections": restored}
