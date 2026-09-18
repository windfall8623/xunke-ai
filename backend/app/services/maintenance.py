"""Operator-only, resumable retention under the exclusive index-owner lock.

SQL pointer removal and a durable cleanup intent commit together. Physical
deletion happens afterwards and is retried after errors or process death.
Business citations, published old builds and uncertain costs are retained.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import timedelta
from types import SimpleNamespace

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load, now
from app.rag.artifact_store import OwnerIndexStore
from app.rag.contracts import stable_hash

DEBUG_DAYS = 30
EVALUATION_DAYS = 90
ORPHAN_GRACE_HOURS = 24
FILE_ROOTS = (
    "raw",
    "assets",
    "sources",
    "snapshots",
    "rag/runs",
    "evaluation/artifacts",
    "evaluation/datasets",
)
TERMINAL_RUNS = ("completed", "cancelled", "failed")
SAMPLE_METADATA = {"sample_id", "case_type", "family_ids", "split", "tags"}
MANIFEST_METADATA = {
    "schema_version",
    "dataset_hash",
    "annotation_version",
    "metric_version",
    "judge_profile_id",
    "judge_config_hash",
    "cache_protocol",
    "context_token_budget",
    "split",
    "repeat_count",
    "dataset_state",
    "sample_clusters",
    "gold_reviewed",
    "release_gold_status",
    "formal_gold_eligible",
    "judge_calibrated",
    "protocol_frozen",
    "planned_sample_ids",
    "pipeline_config_hash",
    "code_hash",
    "runtime_dependencies",
    "retry_policy",
    "cost_estimate",
}
ATTEMPT_METADATA = {
    "event",
    "attempt",
    "at",
    "status",
    "stage",
    "error_code",
    "artifact_hash",
    "worker_id",
    "lease_hash",
    "operation_id",
    "call_id",
    "result_id",
    "usage",
}


def _operator(value, *, apply):
    if value is None and not apply:
        return "dry-run"
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError(
            "Applying maintenance requires an operator identifier (1–120 characters)"
        )
    return value.strip()


def _report(apply):
    return {"dry_run": not apply, "counts": {}, "errors": [], "warnings": []}


def _count(report, name, amount=1):
    report["counts"][name] = report["counts"].get(name, 0) + amount


def _error(report, kind, target_id, exc):
    report["errors"].append(
        {
            "kind": kind,
            "target_id": target_id,
            "code": getattr(exc, "code", type(exc).__name__),
        }
    )


def _scope(owner_id, column="owner_id"):
    return (f" AND {column}=%s", [owner_id]) if owner_id is not None else ("", [])


def _key(store, key):
    return store.resolve_key(key).relative_to(store.root).as_posix()


@dataclass
class References:
    keys: set[str] = field(default_factory=set)
    prefixes: set[str] = field(default_factory=set)
    snapshots_complete: bool = True

    def protects(self, key):
        return (
            key in self.keys
            or any(
                key == prefix or key.startswith(prefix + "/")
                for prefix in self.prefixes
            )
            or (key.startswith("snapshots/") and not self.snapshots_complete)
        )


def _collect_keys(store, value, refs):
    if isinstance(value, list):
        for item in value:
            _collect_keys(store, item, refs)
    elif isinstance(value, dict):
        for name, item in value.items():
            if name == "projection_key" and isinstance(item, str):
                refs.prefixes.add(_key(store, item))
            elif (
                name.endswith("artifact_key") or name == "storage_key"
            ) and isinstance(item, str):
                refs.keys.add(_key(store, item))
            else:
                _collect_keys(store, item, refs)


def _protect_candidate(store, intent, refs):
    projection = OwnerIndexStore._key(SimpleNamespace(**intent))
    if intent["projection_key"] != projection:
        raise ValueError("Candidate projection identity does not match its intent")
    refs.prefixes.add(_key(store, projection))
    # The canonical write precedes attempt/manifest publication. Preserve the
    # known parse directory even if the process died before manifest.json.
    canonical_directory = (
        "sources/"
        + stable_hash(
            [
                intent["owner_id"],
                intent["namespace"],
                intent["doc_id"],
                intent["document_version_id"],
            ]
        )[:32]
    )
    refs.prefixes.add(canonical_directory)
    manifest = store.resolve_key(projection + "/manifest.json")
    if manifest.exists():
        _collect_keys(store, json.loads(manifest.read_bytes()), refs)


async def _references(store):
    """Use every retained SQL reference, including inactive ready builds.

    If retained evidence is missing/unreadable, snapshots are kept wholesale.
    Guessing which missing artifact once cited a snapshot could destroy history.
    """
    refs = References()
    queries = (
        "SELECT storage_key AS artifact_key FROM kb_document_versions",
        "SELECT storage_key AS artifact_key FROM user_assets",
        "SELECT storage_key AS artifact_key FROM kb_nodes",
        "SELECT canonical_artifact_key AS artifact_key,manifest_json FROM kb_index_builds WHERE status='ready'",
        "SELECT artifact_key FROM eval_datasets WHERE status<>'revoked'",
    )
    for sql in queries:
        for row in await fetch_all(sql):
            if row.get("artifact_key"):
                refs.keys.add(_key(store, row["artifact_key"]))
            if row.get("manifest_json"):
                _collect_keys(store, load(row["manifest_json"]), refs)
    for path in store.resolve_key("rag/projections").glob("*/attempt.json"):
        intent = json.loads(path.read_bytes())
        if await _candidate_is_retained(intent):
            if store.resolve_key(intent["projection_key"]) != path.parent.resolve():
                raise ValueError("Candidate intent does not identify its own directory")
            _protect_candidate(store, intent, refs)
    for row in await fetch_all(
        "SELECT evidence_artifact_key,debug_artifact_key FROM rag_runs"
    ):
        for field_name in ("evidence_artifact_key", "debug_artifact_key"):
            key = row[field_name]
            if key:
                refs.keys.add(_key(store, key))
                try:
                    _collect_keys(
                        store, json.loads(store.resolve_key(key).read_bytes()), refs
                    )
                except (OSError, ValueError, TypeError):
                    refs.snapshots_complete = False
    for row in await fetch_all("SELECT artifact_key,artifact_json FROM eval_results"):
        if row["artifact_json"] is not None:
            _collect_keys(store, load(row["artifact_json"]), refs)
        if row["artifact_key"]:
            refs.keys.add(_key(store, row["artifact_key"]))
            try:
                _collect_keys(
                    store,
                    json.loads(store.resolve_key(row["artifact_key"]).read_bytes()),
                    refs,
                )
            except (OSError, ValueError, TypeError):
                refs.snapshots_complete = False
    # Frozen source references can include a web snapshot without a prediction.
    for row in await fetch_all(
        "SELECT manifest_json,samples_json FROM eval_datasets WHERE status<>'revoked'"
    ):
        _collect_keys(store, load(row["manifest_json"]), refs)
        _collect_keys(store, load(row["samples_json"]), refs)
    # Protect a recoverable or in-flight job's entire artifact directory.
    for row in await fetch_all(
        "SELECT task_id FROM quiz_tasks WHERE status IN ('pending','running')"
    ):
        run_directory = "rag_" + digest(row["task_id"])[:32]
        refs.prefixes.update(
            {"rag/runs/" + run_directory, "evaluation/artifacts/" + run_directory}
        )
    return refs


async def _queue(
    store, kind, target_id, keys, metadata, owner_id, operator, *, conn=None
):
    root_hash = digest(str(store.root))
    action_id = digest(dump([root_hash, kind, target_id]))
    await execute(
        "INSERT INTO maintenance_actions(action_id,kind,target_id,owner_id,storage_root_hash,storage_keys_json,metadata_json,operator) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE status='pending',completed_at=NULL,error_code=NULL,operator=%s",
        (
            action_id,
            kind,
            target_id,
            owner_id,
            root_hash,
            dump(keys),
            dump(metadata),
            operator,
            operator,
        ),
        conn=conn,
    )


async def _candidate_is_retained(intent, *, conn=None):
    build = await fetch_one(
        "SELECT status,published_attempt_id FROM kb_index_builds WHERE build_id=%s AND owner_id=%s",
        (intent["index_build_id"], intent["owner_id"]),
        conn=conn,
    )
    if (
        build
        and build["status"] == "ready"
        and build["published_attempt_id"] == intent["attempt_id"]
    ):
        return True
    job = await fetch_one(
        "SELECT task_id FROM quiz_tasks WHERE user_id=%s AND kind='ingest' AND status IN ('pending','running') "
        "AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.build_id'))=%s LIMIT 1",
        (intent["owner_id"], intent["index_build_id"]),
        conn=conn,
    )
    return job is not None


async def _drain(store, report, *, owner_id=None):
    extra, args = _scope(owner_id)
    actions = await fetch_all(
        "SELECT * FROM maintenance_actions WHERE storage_root_hash=%s AND status='pending'"
        + extra
        + " ORDER BY created_at,action_id",
        [digest(str(store.root)), *args],
    )
    refs = await _references(store)
    for action in actions:
        kind, target = action["kind"], action["target_id"]
        try:
            await execute(
                "UPDATE maintenance_actions SET attempts=attempts+1 WHERE action_id=%s",
                (action["action_id"],),
            )
            if kind == "tombstone":
                from app.services.source_service import cleanup_document

                await cleanup_document(action["owner_id"], target, store)
            elif kind == "candidate":
                intent = load(action["metadata_json"])
                if not await _candidate_is_retained(intent):
                    store.delete_attempt(SimpleNamespace(**intent))
            else:
                for key in load(action["storage_keys_json"]):
                    key = _key(store, key)
                    if refs.protects(key):
                        _count(report, "referenced_files_preserved")
                        continue
                    if not any(key.startswith(root + "/") for root in FILE_ROOTS):
                        raise ValueError(
                            "Cleanup key is outside managed artifact directories"
                        )
                    path = store.resolve_key(key)
                    if (
                        kind == "orphan"
                        and path.exists()
                        and path.stat().st_mtime
                        > time.time() - ORPHAN_GRACE_HOURS * 3600
                    ):
                        continue
                    # APIs may upload while the owner is stopped. Recheck SQL
                    # immediately before unlink; a new upload cannot be 24h old.
                    if kind == "orphan" and (await _references(store)).protects(key):
                        continue
                    path.unlink(missing_ok=True)
            await execute(
                "UPDATE maintenance_actions SET status='completed',completed_at=%s,error_code=NULL WHERE action_id=%s",
                (now(), action["action_id"]),
            )
            _count(report, "cleanup_actions_completed")
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            await execute(
                "UPDATE maintenance_actions SET error_code=%s WHERE action_id=%s",
                (code[:64], action["action_id"]),
            )
            _error(report, kind, target, exc)


async def _expire_debug(store, report, operator, owner_id):
    extra, args = _scope(owner_id)
    stamp = now()
    rows = await fetch_all(
        "SELECT run_id,owner_id FROM rag_runs WHERE debug_artifact_key IS NOT NULL "
        "AND (debug_expires_at<=%s OR (debug_expires_at IS NULL AND created_at<=%s))"
        + extra,
        [stamp, stamp - timedelta(days=DEBUG_DAYS), *args],
    )
    for row in rows:
        if report["dry_run"]:
            _count(report, "debug_runs_expired")
            continue
        async with transaction() as conn:
            current = await fetch_one(
                "SELECT * FROM rag_runs WHERE run_id=%s FOR UPDATE",
                (row["run_id"],),
                conn=conn,
            )
            if not current["debug_artifact_key"]:
                continue
            await _queue(
                store,
                "debug",
                row["run_id"],
                [current["debug_artifact_key"]],
                {},
                row["owner_id"],
                operator,
                conn=conn,
            )
            await execute(
                "UPDATE rag_runs SET debug_artifact_key=NULL,debug_hash=NULL WHERE run_id=%s",
                (row["run_id"],),
                conn=conn,
            )
        _count(report, "debug_runs_expired")


def _expired_manifest(raw, stamp):
    result = {name: value for name, value in raw.items() if name in MANIFEST_METADATA}
    # Config and scope hashes keep provenance without retaining arbitrary prompt
    # text, URLs, private document titles or user-supplied manifest extras.
    for name in (
        "source_scopes",
        "pipeline_config",
        "provider_config",
        "scoring_config",
    ):
        if name in raw:
            result[name + "_sha256"] = digest(dump(raw[name]))
    result.update(
        raw_artifacts_status="expired",
        raw_artifacts_expired_at=iso(stamp),
        reproducible=False,
    )
    return result


def _evaluation_due(row, *, dataset_status, held, stamp):
    if (
        row["status"] not in TERMINAL_RUNS
        or load(row["manifest_json"]).get("raw_artifacts_status") == "expired"
    ):
        return False
    if dataset_status == "revoked":
        return True
    return not held and row["created_at"] <= stamp - timedelta(days=EVALUATION_DAYS)


async def _expire_evaluations(store, report, operator, owner_id):
    extra, args = _scope(owner_id, "u.owner_id")
    stamp = now()
    rows = await fetch_all(
        "SELECT u.run_id,u.dataset_id,u.dataset_version FROM eval_runs u "
        "JOIN eval_datasets ds ON ds.dataset_id=u.dataset_id AND ds.version=u.dataset_version "
        "LEFT JOIN eval_retention_holds h ON h.run_id=u.run_id "
        "WHERE u.status IN ('completed','cancelled','failed') AND "
        "((u.created_at<=%s AND h.run_id IS NULL) OR ds.status='revoked')" + extra,
        [stamp - timedelta(days=EVALUATION_DAYS), *args],
    )
    for row in rows:
        async with transaction() as conn:
            # Match scoring/review lock order; a current scoring lease is never
            # invalidated just because a wall-clock retention date elapsed.
            dataset = await fetch_one(
                "SELECT status FROM eval_datasets WHERE dataset_id=%s AND version=%s FOR SHARE",
                (row["dataset_id"], row["dataset_version"]),
                conn=conn,
            )
            current = await fetch_one(
                "SELECT * FROM eval_runs WHERE run_id=%s FOR UPDATE",
                (row["run_id"],),
                conn=conn,
            )
            raw = load(current["manifest_json"])
            held = await fetch_one(
                "SELECT run_id FROM eval_retention_holds WHERE run_id=%s",
                (row["run_id"],),
                conn=conn,
            )
            if not _evaluation_due(
                current, dataset_status=dataset["status"], held=bool(held), stamp=stamp
            ):
                continue
            results = await fetch_all(
                "SELECT * FROM eval_results WHERE run_id=%s FOR UPDATE",
                (row["run_id"],),
                conn=conn,
            )
            if any(
                r["scoring_expires_at"] and r["scoring_expires_at"] > stamp
                for r in results
            ):
                _count(report, "active_scoring_preserved")
                continue
            if await fetch_one(
                "SELECT task_id FROM quiz_tasks WHERE mode='evaluation' AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.run_id'))=%s AND status='running' AND lease_expires_at>%s LIMIT 1",
                (row["run_id"], stamp),
                conn=conn,
            ):
                _count(report, "active_prediction_preserved")
                continue
            if not report["dry_run"]:
                keys = [r["artifact_key"] for r in results if r["artifact_key"]]
                await _queue(
                    store,
                    "evaluation",
                    row["run_id"],
                    keys,
                    {},
                    current["owner_id"],
                    operator,
                    conn=conn,
                )
                for result in results:
                    sample = {
                        k: v
                        for k, v in load(result["sample_json"]).items()
                        if k in SAMPLE_METADATA
                    }
                    attempts = [
                        {k: v for k, v in event.items() if k in ATTEMPT_METADATA}
                        for event in load(result["attempts_json"], [])
                        if isinstance(event, dict)
                    ]
                    await execute(
                        "UPDATE eval_results SET artifact_json=NULL,artifact_key=NULL,sample_json=%s,review_json=NULL,attempts_json=%s,scoring_lease_token=NULL,scoring_expires_at=NULL WHERE result_id=%s",
                        (dump(sample), dump(attempts), result["result_id"]),
                        conn=conn,
                    )
                await execute(
                    "UPDATE eval_runs SET manifest_json=%s WHERE run_id=%s",
                    (dump(_expired_manifest(raw, stamp)), row["run_id"]),
                    conn=conn,
                )
                await execute(
                    "UPDATE quiz_tasks SET scope_json=NULL,result_json=NULL,user_input='',error_message=NULL WHERE mode='evaluation' AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.run_id'))=%s",
                    (row["run_id"],),
                    conn=conn,
                )
            _count(report, "evaluation_runs_expired")


async def _expire_auth(report, owner_id):
    for table, predicate in (
        ("auth_sessions", "(expires_at<=%s OR revoked_at IS NOT NULL)"),
        ("auth_link_codes", "(expires_at<=%s OR used_at IS NOT NULL)"),
        ("auth_rate_limits", "expires_at<=%s"),
    ):
        if table == "auth_rate_limits" and owner_id is not None:
            continue  # IP/account hashes have no trustworthy per-user mapping.
        extra, args = (
            _scope(owner_id, "user_id") if table != "auth_rate_limits" else ("", [])
        )
        params = [now(), *args]
        if report["dry_run"]:
            count = (
                await fetch_one(
                    f"SELECT COUNT(*) AS n FROM {table} WHERE {predicate}" + extra,
                    params,
                )
            )["n"]
        else:
            count = await execute(
                f"DELETE FROM {table} WHERE {predicate}" + extra, params
            )
        _count(report, table + "_expired", count)


async def _tombstones(store, report, operator, owner_id):
    extra, args = _scope(owner_id, "user_id")
    for row in await fetch_all(
        "SELECT doc_id,user_id FROM kb_documents WHERE deleted_at IS NOT NULL" + extra,
        args,
    ):
        _count(report, "tombstones_selected")
        if not report["dry_run"]:
            # Reopen a completed audit too: late residue must never be skipped
            # permanently after a prior cleanup was reported as empty.
            await _queue(
                store, "tombstone", row["doc_id"], [], {}, row["user_id"], operator
            )


async def sweep_orphans(store, *, apply=False, operator=None, owner_id=None):
    """Delete mature unpublished attempts and unreferenced managed files only."""
    store._check_owner()
    operator = _operator(operator, apply=apply)
    report = _report(apply)
    cutoff = time.time() - ORPHAN_GRACE_HOURS * 3600
    refs = await _references(store)
    if not refs.snapshots_complete:
        report["warnings"].append(
            {"code": "unreadable_retained_artifact", "action": "preserve_all_snapshots"}
        )
    for path in store.resolve_key("rag/projections").glob("*/attempt.json"):
        try:
            intent = json.loads(path.read_bytes())
            if owner_id is not None and intent["owner_id"] != owner_id:
                continue
            if any(
                p.stat().st_mtime > cutoff
                for p in path.parent.rglob("*")
                if p.is_file()
            ):
                continue
            if await _candidate_is_retained(intent):
                continue
            if refs.protects(_key(store, intent["projection_key"])):
                continue
            _count(report, "candidate_attempts_selected")
            if apply:
                await _queue(
                    store,
                    "candidate",
                    digest(dump(intent)),
                    [],
                    intent,
                    intent["owner_id"],
                    operator,
                )
        except Exception as exc:
            _error(report, "candidate", digest(path.name), exc)
    # A scoped sweep cannot reliably infer the owner of legacy/unregistered
    # files. Its SQL retention and exact candidate identities are still scoped.
    if owner_id is None:
        for directory in FILE_ROOTS:
            for path in store.resolve_key(directory).rglob("*"):
                if not path.is_file() or path.stat().st_mtime > cutoff:
                    continue
                key = _key(store, path.relative_to(store.root).as_posix())
                if refs.protects(key):
                    continue
                _count(report, "orphan_files_selected")
                if apply:
                    await _queue(
                        store, "orphan", digest(key), [key], {}, None, operator
                    )
    if apply:
        await _drain(store, report, owner_id=owner_id)
    return report


async def run_maintenance(*, apply=False, operator=None, owner_id=None):
    operator = _operator(operator, apply=apply)
    report = _report(apply)
    with OwnerIndexStore(get_settings().data_dir, process_role="rag_owner") as store:
        if apply:
            await _drain(store, report, owner_id=owner_id)
        await _expire_debug(store, report, operator, owner_id)
        await _expire_evaluations(store, report, operator, owner_id)
        await _expire_auth(report, owner_id)
        from app.services.experience_event_service import purge_experience_events

        _count(report, "experience_events_expired", await purge_experience_events(
            owner_id=owner_id, dry_run=not apply,
        ))
        from app.services.content_event_service import purge_content

        _count(report, "content_previews_expired", await purge_content(owner_id=owner_id, dry_run=not apply))
        from app.services.teaching_quality_service import purge_expired_quality_candidates

        _count(report, "teaching_candidates_expired", await purge_expired_quality_candidates(
            owner_id=owner_id, dry_run=not apply,
        ))
        if apply and owner_id is None:
            from app.services import learning_notification_service as reminders

            _count(report, "learning_weekly_digests_scheduled",
                   await reminders.enqueue_weekly_digests(apply=True))
            _count(report, "learning_reminders_delivered",
                   await reminders.deliver_due_reminders(apply=True))
        await _tombstones(store, report, operator, owner_id)
        if apply:
            await _drain(store, report, owner_id=owner_id)
        swept = await sweep_orphans(
            store, apply=apply, operator=operator, owner_id=owner_id
        )
        for name, count in swept["counts"].items():
            _count(report, name, count)
        report["errors"].extend(swept["errors"])
        report["warnings"].extend(swept["warnings"])
    return report


async def hold_evaluation_run(
    *, run_id, operator, reason, basis, authorization_sha256, apply=False
):
    """A local operator receipt, never an end-user manifest flag, grants a hold."""
    operator = _operator(operator, apply=apply)
    if (
        basis not in {"public_release", "self_authored_release"}
        or not isinstance(reason, str)
        or not reason.strip()
        or len(reason) > 500
        or not re.fullmatch(r"[0-9a-fA-F]{64}", authorization_sha256 or "")
    ):
        raise AppError(
            422,
            "retention_authorization_required",
            "长期保留需要明确用途及已核验授权文件的 SHA-256",
        )
    from app.services import eval_dataset_service

    async with transaction() as conn:
        preview = await fetch_one(
            "SELECT * FROM eval_runs WHERE run_id=%s", (run_id,), conn=conn
        )
        if not preview:
            raise not_found()
        dataset = await eval_dataset_service.dataset_row(
            preview["owner_id"],
            preview["dataset_id"],
            preview["dataset_version"],
            conn=conn,
        )
        if dataset["status"] != "frozen":
            raise conflict("dataset_revoked", "只能长期保留仍获授权的冻结评测")
        await eval_dataset_service.hydrate(
            preview["owner_id"],
            load(dataset["manifest_json"]),
            load(dataset["samples_json"]),
            conn=conn,
        )
        dataset = await fetch_one(
            "SELECT status FROM eval_datasets WHERE dataset_id=%s AND version=%s FOR SHARE",
            (preview["dataset_id"], preview["dataset_version"]),
            conn=conn,
        )
        run = await fetch_one(
            "SELECT * FROM eval_runs WHERE run_id=%s FOR UPDATE", (run_id,), conn=conn
        )
        manifest = load(run["manifest_json"])
        if (
            dataset["status"] != "frozen"
            or run["status"] != "completed"
            or manifest.get("raw_artifacts_status") == "expired"
            or manifest.get("reproducible") is False
        ):
            raise conflict(
                "retention_run_ineligible", "只能长期保留已完成且原始工件仍有效的评测"
            )
        if apply:
            old = await fetch_one(
                "SELECT * FROM eval_retention_holds WHERE run_id=%s",
                (run_id,),
                conn=conn,
            )
            if old and (old["basis"], old["authorization_sha256"]) != (
                basis,
                authorization_sha256.lower(),
            ):
                raise conflict(
                    "retention_receipt_conflict", "此运行已有不同的长期保留授权记录"
                )
            if not old:
                await execute(
                    "INSERT INTO eval_retention_holds(run_id,owner_id,operator,reason,basis,authorization_sha256) VALUES(%s,%s,%s,%s,%s,%s)",
                    (
                        run_id,
                        run["owner_id"],
                        operator,
                        reason.strip(),
                        basis,
                        authorization_sha256.lower(),
                    ),
                    conn=conn,
                )
    return {
        "dry_run": not apply,
        "run_id": run_id,
        "retention": "operator_release_hold",
        "basis": basis,
    }
