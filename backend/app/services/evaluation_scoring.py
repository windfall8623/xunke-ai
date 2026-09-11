"""Fenced JSON scoring control plane; no Ragas or vector client is imported here.

The lock order is source authorization, dataset, run, result, then budgets. Calls
are reserved durably before dispatch. A lost response or process never releases
an unknown monetary reservation, and completion never selects the best retry.
"""

from __future__ import annotations

import copy
import json
import math
import re
from datetime import timedelta
from decimal import ROUND_CEILING, Decimal

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict
from app.core.values import digest, dump, iso, load, now, uid
from app.rag.contracts import ResolvedScope
from app.rag.errors import RagError
from app.services import budget_service, eval_dataset_service
from app.services.evaluation_observations import scoring_observations, scoring_store
from app.services.source_service import reauthorize_scope

MAX_SCORING_ATTEMPTS = 2
MAX_JSON_BYTES = 2 * 1024 * 1024


def stale():
    return conflict("stale_scoring_lease", "评分任务已失效或已由其他进程接管")


def _json(value):
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (ValueError, TypeError):
        raise AppError(
            422, "invalid_scoring_payload", "评分内容必须是有限数值的 JSON"
        ) from None
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise AppError(413, "scoring_payload_too_large", "评分内容超过大小限制")
    return encoded


def _events(row):
    return load(row["attempts_json"], [])


def _event(name, row, **fields):
    return {
        "event": name,
        "attempt": row["scoring_attempt"],
        "at": iso(now()),
        **fields,
    }


def _max_attempts(run):
    configured = (
        load(run["manifest_json"])
        .get("retry_policy", {})
        .get("scoring_max_attempts", MAX_SCORING_ATTEMPTS)
    )
    return min(MAX_SCORING_ATTEMPTS, max(1, int(configured)))


async def _locked_context(result_id, conn, *, skip_locked=False):
    # This first read is only a locator. All authorization and state are checked
    # again under locks before a lease, artifact, or call can be returned.
    preview = await fetch_one(
        "SELECT r.run_id,r.sample_id,u.owner_id,u.dataset_id,u.dataset_version,u.manifest_json "
        "FROM eval_results r JOIN eval_runs u ON u.run_id=r.run_id WHERE r.result_id=%s",
        (result_id,),
        conn=conn,
    )
    if not preview:
        raise stale()
    manifest = load(preview["manifest_json"])
    if (
        manifest.get("raw_artifacts_status") == "expired"
        or manifest.get("reproducible") is False
    ):
        raise conflict("raw_artifacts_expired", "原始评测工件已按保留策略清理")
    dataset_preview = await fetch_one(
        "SELECT manifest_json,samples_json,status FROM eval_datasets WHERE dataset_id=%s AND version=%s AND owner_id=%s",
        (preview["dataset_id"], preview["dataset_version"], preview["owner_id"]),
        conn=conn,
    )
    if not dataset_preview or dataset_preview["status"] != "frozen":
        raise conflict("dataset_revoked", "评分数据集已撤销或不再冻结")
    original_sample = next(
        (
            item
            for item in load(dataset_preview["samples_json"])
            if item["sample_id"] == preview["sample_id"]
        ),
        None,
    )
    if original_sample is None:
        raise conflict("sample_checksum_mismatch", "评分样本与冻结数据集不一致")
    try:
        scope = manifest.get("source_scopes", {}).get(preview["sample_id"])
        if scope is not None:
            resolved = ResolvedScope.model_validate(scope)
            if (
                resolved.owner_id != preview["owner_id"]
                or resolved.namespace != f"evaluation:{preview['owner_id']}"
            ):
                raise conflict("source_scope_invalid", "评分资料范围无效")
            await reauthorize_scope(resolved, conn=conn)
        # Hydration acquires source-share locks, including registered sources,
        # before dataset/run locks so deletion can use the same lock order.
        _, hydrated, _ = await eval_dataset_service.hydrate(
            preview["owner_id"],
            load(dataset_preview["manifest_json"]),
            [original_sample],
            conn=conn,
        )
    except (RagError, OSError) as exc:
        raise conflict("source_revoked", "评分原文已撤销或不可读取") from exc
    except AppError as exc:
        if exc.status == 404:
            raise conflict("source_revoked", "评分原文已撤销或不可读取") from exc
        raise
    dataset = await fetch_one(
        "SELECT * FROM eval_datasets WHERE dataset_id=%s AND version=%s AND owner_id=%s FOR SHARE",
        (preview["dataset_id"], preview["dataset_version"], preview["owner_id"]),
        conn=conn,
    )
    run = await fetch_one(
        "SELECT * FROM eval_runs WHERE run_id=%s FOR UPDATE"
        + (" SKIP LOCKED" if skip_locked else ""),
        (preview["run_id"],),
        conn=conn,
    )
    if not run:
        return None
    current_manifest = load(run["manifest_json"])
    if (
        current_manifest.get("raw_artifacts_status") == "expired"
        or current_manifest.get("reproducible") is False
    ):
        raise conflict("raw_artifacts_expired", "原始评测工件已按保留策略清理")
    row = await fetch_one(
        "SELECT * FROM eval_results WHERE result_id=%s FOR UPDATE",
        (result_id,),
        conn=conn,
    )
    if not row or not dataset or dataset["status"] != "frozen":
        raise conflict("dataset_revoked", "评分数据集已撤销或不再冻结")
    if run["status"] in {"cancelled", "failed"}:
        raise conflict("run_stopped", "评测运行已停止")
    if run["deadline_at"] <= now():
        raise conflict("deadline_exceeded", "评测运行已到期")
    frozen = {
        "manifest": load(dataset["manifest_json"]),
        "samples": load(dataset["samples_json"]),
    }
    if (
        digest(dump(frozen)) != dataset["checksum"]
        or manifest.get("dataset_hash") != dataset["checksum"]
    ):
        raise conflict("dataset_checksum_mismatch", "评分数据集校验和不一致")
    sample = next(
        (item for item in frozen["samples"] if item["sample_id"] == row["sample_id"]),
        None,
    )
    if (
        sample is None
        or dump(sample) != dump(original_sample)
        or dump(sample) != dump(load(row["sample_json"]))
    ):
        raise conflict("sample_checksum_mismatch", "评分样本与冻结数据集不一致")
    # The actual source text is hydrated from authorized immutable artifacts;
    # imported client paths or claimed text cannot become judge ground truth.
    return row, run, dataset, hydrated[0]


def _fence(row, lease_token, attempt, *, terminal=False):
    if row["scoring_lease_token"] != lease_token or row["scoring_attempt"] != attempt:
        raise stale()
    if terminal and row["status"] in {"completed", "failed", "pending_scoring"}:
        return
    if (
        row["status"] != "scoring"
        or not row["scoring_expires_at"]
        or row["scoring_expires_at"] <= now()
    ):
        raise stale()


async def _unclaimable(result_id, code):
    # Revocation may happen before the full lock set can be obtained. Reconcile
    # only an unclaimed/expired result; never overwrite another active lease.
    await execute(
        "UPDATE eval_results SET status='failed',error_code=%s,scoring_expires_at=NULL "
        "WHERE result_id=%s AND (status='pending_scoring' OR (status='scoring' AND scoring_expires_at<=UTC_TIMESTAMP(6)))",
        (code, result_id),
    )


async def claim_scoring(worker_id, lease_seconds=120, run_id=None):
    if (
        not isinstance(worker_id, str)
        or not 1 <= len(worker_id) <= 128
        or not 5 <= lease_seconds <= 3600
    ):
        raise AppError(422, "invalid_scoring_claim", "评分任务领取参数无效")
    # Heartbeats are metadata only. Hash long host names to the common 64-char key.
    identity = "eval-" + digest(worker_id)[:40]
    await execute(
        "INSERT INTO worker_heartbeats(worker_id,role,heartbeat_at) VALUES(%s,'eval_scorer',UTC_TIMESTAMP(6)) "
        "ON DUPLICATE KEY UPDATE heartbeat_at=UTC_TIMESTAMP(6),role='eval_scorer'",
        (identity,),
    )
    candidates = await fetch_all(
        "SELECT result_id FROM eval_results WHERE artifact_json IS NOT NULL "
        "AND (status='pending_scoring' OR (status='scoring' AND scoring_expires_at<=UTC_TIMESTAMP(6)))"
        + (" AND run_id=%s" if run_id else "")
        + " ORDER BY created_at,result_id LIMIT 32",
        (run_id,) if run_id else (),
    )
    for candidate in candidates:
        try:
            async with transaction() as conn:
                context = await _locked_context(
                    candidate["result_id"], conn, skip_locked=True
                )
                if context is None:
                    continue
                row, run, _, sample = context
                if row["status"] != "pending_scoring" and not (
                    row["status"] == "scoring"
                    and row["scoring_expires_at"]
                    and row["scoring_expires_at"] <= now()
                ):
                    continue
                events = _events(row)
                if row["status"] == "scoring":
                    events.append(_event("scoring_lease_expired", row))
                if row["scoring_attempt"] >= _max_attempts(run):
                    events.append(_event("scoring_exhausted", row))
                    await execute(
                        "UPDATE eval_results SET status='failed',error_code='scoring_attempts_exhausted',"
                        "scoring_expires_at=NULL,attempts_json=%s WHERE result_id=%s",
                        (dump(events), row["result_id"]),
                        conn=conn,
                    )
                    continue
                row["scoring_attempt"] += 1
                token, expires = (
                    uid("scorelease"),
                    min(now() + timedelta(seconds=lease_seconds), run["deadline_at"]),
                )
                events.append(_event("scoring_claimed", row, worker_id=identity))
                await execute(
                    "UPDATE eval_results SET status='scoring',scoring_attempt=%s,scoring_lease_token=%s,"
                    "scoring_expires_at=%s,attempts_json=%s,error_code=NULL WHERE result_id=%s",
                    (
                        row["scoring_attempt"],
                        token,
                        expires,
                        dump(events),
                        row["result_id"],
                    ),
                    conn=conn,
                )
                config = copy.deepcopy(
                    load(run["manifest_json"]).get("scoring_config", {})
                )
                config.setdefault(
                    "metric_version",
                    load(run["manifest_json"]).get("metric_version", "evidence-v1"),
                )
                config = scoring_observations(
                    sample,
                    load(row["artifact_json"]),
                    config,
                    load(run["manifest_json"])
                    .get("source_scopes", {})
                    .get(row["sample_id"]),
                    store=await scoring_store(
                        sample,
                        load(row["artifact_json"]),
                        load(run["manifest_json"])
                        .get("source_scopes", {})
                        .get(row["sample_id"]),
                        conn=conn,
                    ),
                    reviews=load(row.get("review_json"), {}).get(
                        "question_reviews", []
                    ),
                )
                calls = await fetch_all(
                    "SELECT operation_id,usage_json FROM provider_calls WHERE owner_id=%s AND operation_id LIKE %s ORDER BY operation_id",
                    (run["owner_id"], f"evalscore:{row['result_id']}:%"),
                    conn=conn,
                )
                history = []
                for call in calls:
                    payload = load(call["usage_json"])
                    history.append(
                        {
                            **{
                                key: value
                                for key, value in payload.items()
                                if key in CALL_FIELDS
                            },
                            "attempt": int(call["operation_id"].split(":")[2]),
                        }
                    )
                return {
                    "result_id": row["result_id"],
                    "run_id": run["run_id"],
                    "sample_id": row["sample_id"],
                    "repeat_index": row["repeat_index"],
                    "lease_token": token,
                    "attempt": row["scoring_attempt"],
                    "lease_expires_at": iso(expires),
                    "deadline_at": iso(run["deadline_at"]),
                    "max_scoring_attempts": _max_attempts(run),
                    "sample": sample,
                    "artifact": load(row["artifact_json"]),
                    "config": config,
                    "previous_judge_calls": history,
                }
        except (AppError, RagError) as exc:
            code = getattr(exc, "code", "source_revoked")
            await _unclaimable(candidate["result_id"], code)
    return None


async def heartbeat_scoring(result_id, lease_token, attempt, lease_seconds=120):
    async with transaction() as conn:
        row, run, _, _ = await _locked_context(result_id, conn)
        _fence(row, lease_token, attempt)
        expires = min(now() + timedelta(seconds=lease_seconds), run["deadline_at"])
        await execute(
            "UPDATE eval_results SET scoring_expires_at=%s WHERE result_id=%s",
            (expires, result_id),
            conn=conn,
        )
        worker = next(
            (
                event.get("worker_id")
                for event in reversed(_events(row))
                if event.get("event") == "scoring_claimed"
            ),
            None,
        )
        if worker:
            await execute(
                "UPDATE worker_heartbeats SET heartbeat_at=UTC_TIMESTAMP(6) WHERE worker_id=%s",
                (worker,),
                conn=conn,
            )
    return {"result_id": result_id, "lease_expires_at": iso(expires), "accepted": True}


def _validated_metrics(metrics):
    if not isinstance(metrics, dict) or not metrics or len(metrics) > 256:
        raise AppError(422, "invalid_metrics", "评分指标必须是非空映射")
    normalized = copy.deepcopy(metrics)
    for name, item in normalized.items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-zA-Z0-9_@.:-]{1,128}", name)
            or not isinstance(item, dict)
        ):
            raise AppError(422, "invalid_metrics", "评分指标格式无效")
        status, value, denominator = (
            item.get("status"),
            item.get("value"),
            item.get("denominator"),
        )
        if (
            status not in {"ok", "na", "error"}
            or type(denominator) not in (int, float)
            or not math.isfinite(denominator)
            or denominator < 0
        ):
            raise AppError(422, "invalid_metrics", "评分状态或分母无效")
        if status == "ok" and (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or denominator == 0
        ):
            raise AppError(422, "invalid_metrics", "已完成指标需要有效数值和分母")
        if status != "ok" and value is not None:
            raise AppError(422, "invalid_metrics", "NA 或未知评分不能伪装成数值")
        item.setdefault(
            "applicable_count", item.get("applicable_samples", int(status != "na"))
        )
        item.setdefault(
            "error_count", item.get("failure_count", int(status == "error"))
        )
        item.setdefault("reason", None)
        for field in ("applicable_count", "error_count", "unknown_count"):
            if field in item and (type(item[field]) is not int or item[field] < 0):
                raise AppError(422, "invalid_metrics", "评分计数必须是非负整数")
    _json(normalized)
    return normalized


async def complete_scoring(result_id, lease_token, attempt, metrics, judge_calls=None):
    metrics = _validated_metrics(metrics)
    async with transaction() as conn:
        row, run, _, _ = await _locked_context(result_id, conn)
        _fence(row, lease_token, attempt, terminal=True)
        if row["status"] == "completed":
            if dump(load(row["metrics_json"])) != dump(metrics):
                raise conflict(
                    "scoring_completion_conflict", "相同评分尝试的结果不能改变"
                )
            return {"result_id": result_id, "status": "completed", "accepted": True}
        if row["status"] != "scoring":
            raise stale()
        for call in judge_calls or []:
            await _journal(row, run, call, conn)
        events = [
            *_events(row),
            _event("scoring_completed", row, metrics_hash=digest(dump(metrics))),
        ]
        await execute(
            "UPDATE eval_results SET status='completed',metrics_json=%s,error_code=NULL,"
            "scoring_expires_at=NULL,attempts_json=%s WHERE result_id=%s",
            (dump(metrics), dump(events), result_id),
            conn=conn,
        )
    return {"result_id": result_id, "status": "completed", "accepted": True}


async def fail_scoring(result_id, lease_token, attempt, error_code, judge_calls=None):
    if not re.fullmatch(r"[a-z0-9_]{1,64}", error_code):
        raise AppError(422, "invalid_error_code", "评分错误代码无效")
    async with transaction() as conn:
        row, run, _, _ = await _locked_context(result_id, conn)
        _fence(row, lease_token, attempt, terminal=True)
        if row["status"] in {"failed", "pending_scoring"}:
            if row["error_code"] != error_code:
                raise conflict(
                    "scoring_failure_conflict", "相同评分尝试的失败记录不能改变"
                )
            return {"result_id": result_id, "status": row["status"], "accepted": True}
        if row["status"] != "scoring":
            raise stale()
        for call in judge_calls or []:
            await _journal(row, run, call, conn)
        retriable = error_code in {
            "scoring_error",
            "control_transport_error",
            "worker_unavailable",
        }
        status = (
            "pending_scoring"
            if retriable and attempt < _max_attempts(run)
            else "failed"
        )
        events = [*_events(row), _event("scoring_failed", row, error_code=error_code)]
        await execute(
            "UPDATE eval_results SET status=%s,error_code=%s,scoring_expires_at=NULL,attempts_json=%s WHERE result_id=%s",
            (status, error_code, dump(events), result_id),
            conn=conn,
        )
    return {"result_id": result_id, "status": status, "accepted": True}


CALL_FIELDS = {
    "call_id",
    "attempt",
    "stage",
    "status",
    "reserved_cost_cny",
    "cost_cny",
    "cost_status",
    "input_tokens",
    "output_tokens",
    "input_token_details",
    "model",
    "prompt_hash",
    "provider_request_id",
    "provider",
    "provider_model",
    "input_token_upper_bound",
    "operation",
    "price_date",
    "latency_ms",
    "usage_status",
}


def _call_payload(call):
    if not isinstance(call, dict) or set(call) - CALL_FIELDS:
        raise AppError(422, "invalid_call_record", "调用记录只允许去除原文的用量字段")
    call = copy.deepcopy(call)
    if "provider" in call and (
        not isinstance(call["provider"], str)
        or call["provider"] not in {"anthropic", "openai_compatible"}
    ):
        raise AppError(422, "invalid_call_record", "评分调用模型协议无效")
    identifier, status = call.get("call_id"), call.get("status")
    if not isinstance(identifier, str) or not re.fullmatch(
        r"[a-zA-Z0-9_-]{1,128}", identifier
    ):
        raise AppError(422, "invalid_call_record", "调用标识无效")
    if call.get("stage") != "judge" or status not in {
        "reserved",
        "completed",
        "failed",
        "timeout",
        "unknown",
    }:
        raise AppError(422, "invalid_call_record", "评分调用阶段或状态无效")
    if call.get("cost_status", "unknown") not in {
        "unknown",
        "estimated",
        "provider_reported",
    }:
        raise AppError(422, "invalid_call_record", "调用费用状态无效")
    for field in ("reserved_cost_cny", "cost_cny", "latency_ms"):
        value = call.get(field)
        if value is not None and (
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
        ):
            raise AppError(422, "invalid_call_record", "调用费用与耗时必须是有限非负值")
    for field in (
        "input_tokens",
        "output_tokens",
        "input_token_upper_bound",
        "attempt",
    ):
        value = call.get(field)
        if value is not None and (type(value) is not int or value < 0):
            raise AppError(422, "invalid_call_record", "调用 token 与尝试次数无效")
    details = call.get("input_token_details", {})
    if not isinstance(details, dict) or set(details) - {
        "cache_read",
        "cache_creation",
        "ephemeral_5m_input_tokens",
        "ephemeral_1h_input_tokens",
    }:
        raise AppError(
            422, "invalid_call_record", "缓存用量仅允许经过校验的 token 计数"
        )
    for value in details.values():
        if value is not None and (type(value) is not int or value < 0):
            raise AppError(422, "invalid_call_record", "缓存用量必须是非负整数或未知值")
    read, creation = details.get("cache_read", 0), details.get("cache_creation", 0)
    inputs = call.get("input_tokens")
    if (
        inputs is not None
        and read is not None
        and creation is not None
        and read + creation > inputs
    ):
        raise AppError(422, "invalid_call_record", "缓存 token 不能超过总输入")
    if call.get("cost_cny") is not None and any(
        value is None for value in details.values()
    ):
        raise AppError(422, "invalid_call_record", "缓存用量未知时不能提交确定费用")
    if (
        call.get("cost_cny") is not None
        and call.get("cost_status", "unknown") == "unknown"
    ):
        raise AppError(422, "invalid_call_record", "未知费用不能包含确定数额")
    for value in call.values():
        if isinstance(value, str) and len(value) > 256:
            raise AppError(422, "invalid_call_record", "调用元数据过长")
    _json(call)
    return call


async def _journal(row, run, payload, conn):
    call = _call_payload(payload)
    operation_id = f"evalscore:{row['result_id']}:{row['scoring_attempt']}:{digest(call['call_id'])[:32]}"
    old = await fetch_one(
        "SELECT * FROM provider_calls WHERE call_id=%s FOR UPDATE",
        (operation_id,),
        conn=conn,
    )
    if old is None:
        ceiling = call.get("reserved_cost_cny")
        if call["status"] != "reserved" or ceiling is None or ceiling <= 0:
            raise conflict("call_reservation_required", "评分调用必须先预留费用再发送")
        s, day = get_settings(), now().date().isoformat()
        config = (
            load(run["manifest_json"])
            .get("scoring_config", {})
            .get("external_judge", {})
        )
        max_calls = min(100, max(1, int(config.get("max_llm_calls", 32))))
        await budget_service.reserve_budget(
            operation_id,
            "calls",
            1,
            [
                (
                    f"evaluation:user:{run['owner_id']}:{day}:llm",
                    s.user_daily_llm_calls,
                ),
                (f"evaluation:global:{day}:llm", s.eval_daily_llm_calls),
                (
                    f"evalscore:{row['result_id']}:{row['scoring_attempt']}:calls",
                    max_calls,
                ),
            ],
            conn=conn,
        )
        await budget_service.settle_budget(operation_id, "calls", 1, conn=conn)
        reserved = Decimal(str(ceiling)).quantize(
            Decimal(".000001"), rounding=ROUND_CEILING
        )
        await budget_service.reserve_budget(
            operation_id,
            "cny",
            reserved,
            [
                (f"eval_run:{run['run_id']}:cny", run["max_cost_cny"]),
                (f"evaluation:global:{day}:cny", s.eval_daily_cost_cny),
            ],
            conn=conn,
        )
        await execute(
            "INSERT INTO provider_calls(call_id,operation_id,owner_id,mode,stage,status,usage_json) VALUES(%s,%s,%s,'evaluation','judge','reserved',%s)",
            (
                operation_id,
                operation_id,
                run["owner_id"],
                dump(
                    {
                        **call,
                        "lease_fingerprint": digest(row["scoring_lease_token"]),
                        "events": [call],
                    }
                ),
            ),
            conn=conn,
        )
        return {"call_id": call["call_id"], "status": "reserved", "accepted": True}
    saved = load(old["usage_json"])
    events = saved.get("events", [])
    if call in events:
        return {"call_id": call["call_id"], "status": old["status"], "accepted": True}
    if call["status"] == "reserved":
        raise conflict("call_reservation_conflict", "相同调用的预留参数不能改变")
    if call.get("reserved_cost_cny", saved.get("reserved_cost_cny")) != saved.get(
        "reserved_cost_cny"
    ):
        raise conflict("call_reservation_conflict", "相同调用的费用上限不能改变")
    if saved.get("cost_status") != "unknown" and saved.get("cost_cny") is not None:
        raise conflict("call_settlement_conflict", "已结算的调用不能被覆盖")
    merged = {**{key: value for key, value in saved.items() if key != "events"}, **call}
    actual = merged.get("cost_cny")
    if actual is not None and actual > saved["reserved_cost_cny"]:
        raise conflict(
            "call_cost_ceiling_exceeded", "实际用量超过预留，需保留未知费用并核对账单"
        )
    known = actual is not None and merged.get("cost_status") in {
        "estimated",
        "provider_reported",
    }
    rounded_actual = (
        Decimal(str(actual)).quantize(Decimal(".000001"), rounding=ROUND_CEILING)
        if known
        else None
    )
    await budget_service.settle_budget(
        operation_id, "cny", rounded_actual, unknown=not known, conn=conn
    )
    await execute(
        "UPDATE provider_calls SET status=%s,usage_json=%s WHERE call_id=%s",
        (merged["status"], dump({**merged, "events": [*events, call]}), operation_id),
        conn=conn,
    )
    return {"call_id": call["call_id"], "status": merged["status"], "accepted": True}


async def journal_call(result_id, lease_token, attempt, call):
    call = _call_payload(call)
    if call["status"] != "reserved":
        # This branch only updates a previously reserved receipt. It can never
        # read source text or authorize another model request, so billing remains
        # reconcilable after revocation, lease handoff, cancellation or deadline.
        operation_id = f"evalscore:{result_id}:{attempt}:{digest(call['call_id'])[:32]}"
        async with transaction() as conn:
            old = await fetch_one(
                "SELECT * FROM provider_calls WHERE call_id=%s FOR UPDATE",
                (operation_id,),
                conn=conn,
            )
            if old is None or load(old["usage_json"]).get(
                "lease_fingerprint"
            ) != digest(lease_token):
                raise stale()
            run = await fetch_one(
                "SELECT u.* FROM eval_runs u JOIN eval_results r ON r.run_id=u.run_id WHERE r.result_id=%s AND u.owner_id=%s",
                (result_id, old["owner_id"]),
                conn=conn,
            )
            if not run:
                raise stale()
            row = {"result_id": result_id, "scoring_attempt": attempt}
            return await _journal(row, run, call, conn)
    run_id = None
    try:
        async with transaction() as conn:
            row, run, _, _ = await _locked_context(result_id, conn)
            run_id = run["run_id"]
            _fence(row, lease_token, attempt)
            return await _journal(row, run, call, conn)
    except AppError as exc:
        if exc.code == "budget_exceeded" and run_id:
            await execute(
                "UPDATE eval_runs SET status='failed',stop_reason='budget_exceeded' "
                "WHERE run_id=%s AND status NOT IN ('cancelled','completed','failed')",
                (run_id,),
            )
        raise
