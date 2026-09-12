"""SQL ownership, publication and write receipts for physical vector projections.

External calls never run in a SQL transaction. A verified physical projection is
readable only together with the published build and current source permission.
Uncertain writes remain recorded and block publication/deletion/switch checks.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import conflict
from app.core.values import dump, load, uid, now, iso
from app.rag.contracts import stable_hash
from app.rag.errors import SourceUnavailable
from app.rag.vector_store import DeleteReceipt, ProjectionRef, WriteReceipt

_execution = ContextVar("vector_execution", default=None)
_maintenance = ContextVar("vector_maintenance", default=False)


def maintenance_lock_name():
    return "xunke_vector_" + stable_hash(get_settings().mysql_database)[:32]


@contextmanager
def maintenance_context():
    token = _maintenance.set(True)
    try:
        yield
    finally:
        _maintenance.reset(token)


async def assert_not_maintenance(*, conn=None):
    if _maintenance.get():
        return
    lock = await fetch_one("SELECT IS_USED_LOCK(%s) AS holder", (maintenance_lock_name(),), conn=conn)
    if lock and lock["holder"] is not None:
        raise conflict("vector_maintenance", "向量维护正在进行，请稍后重试")


async def _persist(awaitable):
    """Drain receipt persistence even if cancellation arrives more than once."""
    task = asyncio.create_task(awaitable)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


def enabled() -> bool:
    settings = get_settings()
    return settings.vector_backend == "qdrant" or settings.vector_projection_registry_required


def _key(ref):
    return (ref.projection_key, ref.backend, ref.target_revision)


def current_job():
    value = _execution.get()
    return value[0] if value else None


async def _check_writer(ref, conn, *, allow_revoked=False):
    await assert_not_maintenance(conn=conn)
    value = _execution.get()
    if value:
        from app.services.job_service import locked_job

        await locked_job(value[0], conn)
    source = await fetch_one(
        "SELECT namespace,deleted_at,document_revision FROM kb_documents WHERE doc_id=%s AND user_id=%s FOR SHARE",
        (ref.doc_id, ref.owner_id), conn=conn,
    )
    if not source or source["namespace"] != ref.namespace:
        raise SourceUnavailable("Projection source identity is unavailable")
    if source["deleted_at"] is not None and not allow_revoked:
        raise SourceUnavailable("Projection source was revoked")
    if value and value[0]["kind"] == "ingest":
        revision = value[0]["request"].get("document_revision")
        if revision != source["document_revision"]:
            raise SourceUnavailable("Projection source changed while building")


async def register_candidate(ref: ProjectionRef, *, migration_run_id=None, allow_revoked=False):
    """Register ownership before creating archives or sending an external write."""
    value = _execution.get()
    job, worker_id = value if value else ({}, None)
    async with transaction() as conn:
        await _check_writer(ref, conn, allow_revoked=allow_revoked)
        prior = await fetch_one(
            "SELECT * FROM rag_vector_projections WHERE projection_key=%s AND backend=%s AND target_revision=%s FOR UPDATE",
            _key(ref), conn=conn,
        )
        if prior:
            if ProjectionRef.model_validate(load(prior["ref_json"])) != ref:
                raise SourceUnavailable("Registered projection identity cannot change")
            if prior["status"] in {"deleting", "deleted"}:
                raise SourceUnavailable("Projection is pending deletion")
            return prior
        await execute(
            "INSERT INTO rag_vector_projections(projection_key,backend,target_revision,owner_id,namespace,doc_id,ref_json,task_id,task_attempt,worker_id,migration_run_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (*_key(ref), ref.owner_id, ref.namespace, ref.doc_id, dump(ref), job.get("task_id"), job.get("attempt"), worker_id, migration_run_id),
            conn=conn,
        )
    return None


async def attach_archive(ref, archive, expected):
    fields = ("projection_key", "owner_id", "namespace", "doc_id", "document_version_id", "parse_artifact_id", "index_build_id", "attempt_id", "index_profile_hash", "embedding_signature_hash")
    if any(getattr(archive, field) != getattr(ref, field) for field in fields):
        raise SourceUnavailable("Archive does not belong to the registered projection")
    if (archive.count != expected.expected_node_count or archive.dimensions != expected.dimensions
        or archive.node_set_hash != expected.node_set_hash or archive.source_vectors_hash != expected.source_vectors_hash):
        raise SourceUnavailable("Archive and expected projection digest differ")
    async with transaction() as conn:
        await _check_writer(ref, conn)
        row = await fetch_one(
            "SELECT source_vectors_hash,status,ref_json FROM rag_vector_projections WHERE projection_key=%s AND backend=%s AND target_revision=%s FOR UPDATE",
            _key(ref), conn=conn,
        )
        if not row or row["status"] in {"deleting", "deleted"}:
            raise SourceUnavailable("Projection registration is unavailable")
        if ProjectionRef.model_validate(load(row["ref_json"])) != ref:
            raise SourceUnavailable("Registered projection identity cannot change")
        if row["source_vectors_hash"] and row["source_vectors_hash"] != archive.source_vectors_hash:
            raise SourceUnavailable("Immutable projection archive differs")
        await execute(
            "UPDATE rag_vector_projections SET archive_json=%s,expected_json=%s,source_vectors_hash=%s WHERE projection_key=%s AND backend=%s AND target_revision=%s",
            (dump(archive), dump(expected), archive.source_vectors_hash, *_key(ref)), conn=conn,
        )


async def begin_operation(ref, kind, *, rows=None):
    if kind not in {"write", "delete"}:
        raise ValueError("Unknown vector operation kind")
    value = _execution.get()
    job, worker_id = value if value else ({}, None)
    operation_id = uid("vop")
    async with transaction() as conn:
        await _check_writer(ref, conn, allow_revoked=kind == "delete")
        row = await fetch_one(
            "SELECT status,archive_json,ref_json FROM rag_vector_projections WHERE projection_key=%s AND backend=%s AND target_revision=%s FOR UPDATE",
            _key(ref), conn=conn,
        )
        if not row or (kind == "write" and (row["status"] not in {"writing", "failed"} or not row["archive_json"])):
            raise SourceUnavailable("Vector write has no registered source archive")
        if ProjectionRef.model_validate(load(row["ref_json"])) != ref:
            raise SourceUnavailable("Registered operation identity differs")
        if kind == "delete" and row["status"] != "deleting":
            raise SourceUnavailable("Projection must be marked deleting before a delete operation")
        pending = await fetch_one(
            "SELECT operation_id FROM rag_vector_operations WHERE projection_key=%s AND backend=%s AND target_revision=%s AND status<>'finished' AND recovery_json IS NULL LIMIT 1",
            _key(ref), conn=conn,
        )
        if pending:
            raise conflict("vector_operation_unconfirmed", "向量操作尚未确认收尾，请完成恢复后重试")
        await execute(
            "INSERT INTO rag_vector_operations(operation_id,projection_key,backend,target_revision,operation_kind,batch_hash,task_id,task_attempt,worker_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (operation_id, *_key(ref), kind, stable_hash([r.model_dump(mode="json") for r in rows]) if rows else None,
             job.get("task_id"), job.get("attempt"), worker_id), conn=conn,
        )
    return operation_id


async def finish_operation(operation_id, *, receipt=None, error=None):
    confirmed = (
        isinstance(receipt, WriteReceipt) and receipt.status == "completed" and receipt.batch_count == 1
    ) or (
        isinstance(receipt, DeleteReceipt) and receipt.status == "completed" and receipt.remaining_visible == 0
    )
    provider_id = getattr(receipt or error, "provider_operation_id", None)
    provider_status = getattr(receipt, "status", None) or getattr(error, "provider_status", None)
    await execute(
        "UPDATE rag_vector_operations SET status=%s,provider_operation_id=%s,provider_status=%s,error_code=%s,finished_at=IF(%s,UTC_TIMESTAMP(6),NULL) WHERE operation_id=%s AND status='started'",
        ("finished" if confirmed else "unknown", str(provider_id) if provider_id is not None else None,
         provider_status, None if confirmed else "vector_operation_unconfirmed", confirmed, operation_id),
    )


async def recorded_call(ref, kind, callback, *, rows=None):
    operation_id = await begin_operation(ref, kind, rows=rows)
    try:
        receipt = await callback()
    except BaseException as exc:
        # Cancellation of a client request does not undo its server-side effect.
        await _persist(finish_operation(operation_id, error=exc))
        raise
    await _persist(finish_operation(operation_id, receipt=receipt))
    if receipt.status != "completed":
        raise conflict("vector_operation_unconfirmed", "向量操作尚未确认完成")
    return receipt


async def record_verified(ref, verified, *, publish_physical=False):
    async with transaction() as conn:
        await _check_writer(ref, conn)
        row = await fetch_one(
            "SELECT status,source_vectors_hash,expected_json,ref_json FROM rag_vector_projections WHERE projection_key=%s AND backend=%s AND target_revision=%s FOR UPDATE",
            _key(ref), conn=conn,
        )
        if not row or row["status"] in {"deleting", "deleted"}:
            raise SourceUnavailable("Projection was removed before verification")
        pending = await fetch_one(
            "SELECT operation_id FROM rag_vector_operations WHERE projection_key=%s AND backend=%s AND target_revision=%s AND status<>'finished' AND recovery_json IS NULL LIMIT 1",
            _key(ref), conn=conn,
        )
        if pending or row["source_vectors_hash"] != verified.digest.source_vectors_hash:
            raise SourceUnavailable("Projection has uncertain writes or an invalid source hash")
        expected = load(row["expected_json"], {})
        if (ProjectionRef.model_validate(load(row["ref_json"])) != ref or verified.projection_key != ref.projection_key
            or any(expected.get(field) != getattr(verified.digest, field) for field in ("expected_node_count", "dimensions", "node_set_hash", "source_vectors_hash"))
            or not verified.digest.target_vectors_hash):
            raise SourceUnavailable("Verified projection does not match its registered source digest")
        await execute(
            "UPDATE rag_vector_projections SET verified_json=%s,target_vectors_hash=%s,verified_at=UTC_TIMESTAMP(6),status=%s WHERE projection_key=%s AND backend=%s AND target_revision=%s",
            (dump(verified), verified.digest.target_vectors_hash, "ready" if publish_physical else "writing", *_key(ref)), conn=conn,
        )


async def publish_candidate(result, conn):
    """Called inside the existing lease/source CAS publication transaction."""
    s = get_settings()
    row = await fetch_one(
        "SELECT * FROM rag_vector_projections WHERE projection_key=%s AND backend=%s AND target_revision=%s FOR UPDATE",
        (result.projection_key, s.vector_backend, s.vector_target_revision), conn=conn,
    )
    if not row or row["status"] not in {"writing", "ready"} or not row["verified_json"]:
        raise SourceUnavailable("Physical vector projection has not been verified")
    ref = ProjectionRef.model_validate(load(row["ref_json"]))
    for field in ("owner_id", "namespace", "doc_id", "document_version_id", "parse_artifact_id", "index_build_id", "attempt_id", "index_profile_hash"):
        if getattr(ref, field) != getattr(result, field):
            raise SourceUnavailable("Published build and physical projection differ")
    pending = await fetch_one(
        "SELECT operation_id FROM rag_vector_operations WHERE projection_key=%s AND backend=%s AND target_revision=%s AND status<>'finished' AND recovery_json IS NULL LIMIT 1",
        _key(ref), conn=conn,
    )
    if pending:
        raise SourceUnavailable("An uncertain write cannot be published")
    await execute(
        "UPDATE rag_vector_projections SET status='ready' WHERE projection_key=%s AND backend=%s AND target_revision=%s",
        _key(ref), conn=conn,
    )


async def require_ready(manifest, *, backend=None, target_revision=None, conn=None):
    s = get_settings()
    row = await fetch_one(
        "SELECT ref_json FROM rag_vector_projections WHERE projection_key=%s AND backend=%s AND target_revision=%s AND owner_id=%s AND doc_id=%s AND status='ready' AND verified_json IS NOT NULL",
        (manifest.projection_key, backend or s.vector_backend, target_revision or s.vector_target_revision, manifest.owner_id, manifest.doc_id), conn=conn,
    )
    if not row:
        raise SourceUnavailable("Required vector projection is not ready for this backend")
    ref = ProjectionRef.model_validate(load(row["ref_json"]))
    for field in ("namespace", "document_version_id", "parse_artifact_id", "index_build_id", "attempt_id", "index_profile_hash"):
        expected = getattr(manifest, field, None)
        if expected and expected != getattr(ref, field):
            raise SourceUnavailable("Physical projection differs from the authorized source")
    return ref


def _document_ids(job):
    request, scope = job.get("request") or {}, job.get("scope") or {}
    ids = {d["doc_id"] for d in scope.get("documents", []) if d.get("doc_id")}
    if request.get("doc_id"):
        ids.add(request["doc_id"])
    return sorted(ids)


@asynccontextmanager
async def execution_receipt(job, worker_id):
    if not enabled():
        yield
        return
    receipt_id = stable_hash([job["task_id"], job["attempt"], worker_id])
    async with transaction() as conn:
        from app.services.job_service import locked_job

        await assert_not_maintenance(conn=conn)
        await locked_job(job, conn)
        await execute(
            "INSERT INTO rag_execution_receipts(receipt_id,task_id,attempt,worker_id,owner_id,kind,document_ids_json) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (receipt_id, job["task_id"], job["attempt"], worker_id, job["user_id"], job["kind"], dump(_document_ids(job))), conn=conn,
        )
    token = _execution.set((job, worker_id))
    try:
        yield
    finally:
        _execution.reset(token)
        # This runs after the managed task has drained local IO. Unknown remote
        # operations remain separate and still prevent cleanup/publication.
        await _persist(execute(
            "UPDATE rag_execution_receipts SET status='finished',finished_at=UTC_TIMESTAMP(6) WHERE receipt_id=%s",
            (receipt_id,),
        ))


async def assert_document_drained(owner, doc_id):
    rows = await fetch_all(
        "SELECT task_id,kind,document_ids_json FROM rag_execution_receipts WHERE owner_id=%s AND status<>'finished' AND recovery_json IS NULL",
        (owner,),
    )
    for row in rows:
        if row["kind"] != "delete" and doc_id in load(row["document_ids_json"], []):
            raise conflict("cleanup_pending", "相关任务尚未完成执行收尾，资料清理将重试")
    unknown = await fetch_one(
        "SELECT o.operation_id FROM rag_vector_operations o JOIN rag_vector_projections p USING(projection_key,backend,target_revision) "
        "WHERE p.owner_id=%s AND p.doc_id=%s AND o.status<>'finished' AND o.recovery_json IS NULL LIMIT 1", (owner, doc_id),
    )
    if unknown:
        raise conflict("cleanup_pending", "向量写入收尾尚未确认，保留撤权状态并等待清理")


async def document_projections(owner, doc_id, *, include_deleted=False):
    status_clause = "" if include_deleted else " AND status<>'deleted'"
    return await fetch_all(
        "SELECT * FROM rag_vector_projections WHERE owner_id=%s AND doc_id=%s"
        + status_clause + " ORDER BY projection_key,backend,target_revision",
        (owner, doc_id),
    )


async def mark_deleting(ref):
    await execute(
        "UPDATE rag_vector_projections SET status='deleting' WHERE projection_key=%s AND backend=%s AND target_revision=%s AND status<>'deleted'",
        _key(ref),
    )


async def mark_deleted(ref):
    await assert_document_drained(ref.owner_id, ref.doc_id)
    async with transaction() as conn:
        row = await fetch_one(
            "SELECT status FROM rag_vector_projections WHERE projection_key=%s AND backend=%s AND target_revision=%s FOR UPDATE",
            _key(ref), conn=conn,
        )
        if not row or row["status"] not in {"deleting", "deleted"}:
            raise SourceUnavailable("Projection is not pending deletion")
        if row["status"] == "deleted":
            return
        completion = await fetch_one(
            "SELECT MAX(IF(operation_kind='delete' AND status='finished',finished_at,NULL)) AS last_delete,"
            "MAX(IF(operation_kind='write',COALESCE(recovered_at,finished_at,started_at),NULL)) AS last_write "
            "FROM rag_vector_operations WHERE projection_key=%s AND backend=%s AND target_revision=%s",
            _key(ref), conn=conn,
        )
        if not completion["last_delete"] or (completion["last_write"] and completion["last_delete"] < completion["last_write"]):
            raise SourceUnavailable("Projection deletion has no completed visibility receipt")
        await execute(
            "UPDATE rag_vector_projections SET status='deleted' WHERE projection_key=%s AND backend=%s AND target_revision=%s",
            _key(ref), conn=conn,
        )


async def prepare_rewrite(ref):
    """An explicit maintenance repair can replace an invalid physical copy."""
    if not _maintenance.get():
        raise SourceUnavailable("Rewriting a published projection requires maintenance")
    async with transaction() as conn:
        await _check_writer(ref, conn)
        pending = await fetch_one(
            "SELECT operation_id FROM rag_vector_operations WHERE projection_key=%s AND backend=%s AND target_revision=%s AND status<>'finished' AND recovery_json IS NULL LIMIT 1",
            _key(ref), conn=conn,
        )
        if pending:
            raise SourceUnavailable("Unconfirmed operations must be recovered before rewriting")
        await execute(
            "UPDATE rag_vector_projections SET status='writing',verified_json=NULL,verified_at=NULL,target_vectors_hash=NULL "
            "WHERE projection_key=%s AND backend=%s AND target_revision=%s AND status IN ('writing','ready','failed')",
            _key(ref), conn=conn,
        )


async def recover_after_exit(proof, *, qdrant_startup=None):
    """Retire crashed executions with explicit exit evidence and a server restart barrier.

    Original started/unknown statuses remain untouched. This only permits
    deterministic replay or cleanup; publication still requires full verification.
    """
    if not _maintenance.get() or not isinstance(proof, dict):
        raise SourceUnavailable("Recovery requires an explicit maintenance proof")
    if proof.get("format_version") != "vector-recovery.v1" or proof.get("database") != get_settings().mysql_database:
        raise SourceUnavailable("Recovery proof does not identify this database")

    def exit_info(item):
        if not isinstance(item, dict) or not isinstance(item.get("evidence"), str) or not 8 <= len(item["evidence"]) <= 2048:
            raise SourceUnavailable("Recovery requires recorded worker exit evidence")
        try:
            stamp = datetime.fromisoformat(item["exited_at"])
            if stamp.tzinfo is None:
                raise ValueError
            stamp = stamp.astimezone(timezone.utc).replace(tzinfo=None)
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceUnavailable("Recovery exit time requires an explicit timezone") from exc
        if stamp > now() + timedelta(seconds=5):
            raise SourceUnavailable("Recovery exit evidence cannot be in the future")
        return stamp, item["evidence"]

    workers = {}
    for worker in proof.get("workers", []):
        worker_id = worker.get("worker_id") if isinstance(worker, dict) else None
        if not isinstance(worker_id, str) or not worker_id or worker_id in workers:
            raise SourceUnavailable("Recovery proof contains an invalid worker identity")
        workers[worker_id] = exit_info(worker)
    maintenance_exit = exit_info(proof["maintenance_exit"]) if proof.get("maintenance_exit") else None
    if qdrant_startup is not None:
        if not isinstance(qdrant_startup, datetime) or qdrant_startup.tzinfo is None:
            raise SourceUnavailable("Qdrant startup proof is unavailable")
        qdrant_startup = qdrant_startup.astimezone(timezone.utc).replace(tzinfo=None)
    async with transaction() as conn:
        receipts = await fetch_all("SELECT * FROM rag_execution_receipts WHERE status<>'finished' AND recovery_json IS NULL FOR UPDATE", conn=conn)
        operations = await fetch_all("SELECT * FROM rag_vector_operations WHERE status<>'finished' AND recovery_json IS NULL FOR UPDATE", conn=conn)
        evidence_hash = stable_hash(proof)
        changes = []
        for table, rows, key in (("rag_execution_receipts", receipts, "receipt_id"), ("rag_vector_operations", operations, "operation_id")):
            for row in rows:
                exited = workers.get(row["worker_id"]) if row["worker_id"] else maintenance_exit
                if exited is None or exited[0] < row["started_at"]:
                    raise SourceUnavailable("Recovery proof must cover every unfinished executor")
                if table == "rag_vector_operations" and row["backend"] == "qdrant":
                    if qdrant_startup is None or qdrant_startup <= max(row["started_at"], exited[0]):
                        raise SourceUnavailable("Restart Qdrant after the original writers exit before recovering unknown operations")
                audit = {
                    "format_version": "vector-recovery.v1", "proof_hash": evidence_hash,
                    "worker_exited_at": iso(exited[0]), "exit_evidence": exited[1],
                    "qdrant_startup": iso(qdrant_startup) if qdrant_startup else None,
                    "resolution": "executor_exited_replay_required",
                }
                changes.append((table, key, row[key], audit))
        for worker_id, (stamp, _) in workers.items():
            heartbeat = await fetch_one("SELECT heartbeat_at FROM worker_heartbeats WHERE worker_id=%s FOR UPDATE", (worker_id,), conn=conn)
            if heartbeat and heartbeat["heartbeat_at"] > stamp:
                raise SourceUnavailable("A worker heartbeat is newer than its claimed exit")
        for table, key, identity, audit in changes:
            await execute(
                f"UPDATE {table} SET recovery_json=%s,recovered_at=UTC_TIMESTAMP(6) WHERE {key}=%s AND recovery_json IS NULL",
                (dump(audit), identity), conn=conn,
            )
        # Preserve the exit audit above; an old heartbeat is no longer an active worker.
        for worker_id, (stamp, _) in workers.items():
            if any(row["worker_id"] == worker_id for row in receipts):
                await execute("DELETE FROM worker_heartbeats WHERE worker_id=%s AND heartbeat_at<=%s", (worker_id, stamp), conn=conn)
    return {"recovered_operations": len(operations), "retired_executions": len(receipts), "proof_hash": evidence_hash}
