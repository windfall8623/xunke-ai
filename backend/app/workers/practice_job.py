"""Owner-process practice generation, fenced publication and durable usage."""

from __future__ import annotations

import logging
import math
from decimal import Decimal, InvalidOperation

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import conflict, not_found
from app.core.values import digest, load, now
from app.learning.contracts import QuestionConceptBinding
from app.practice.contracts import PracticeArtifact, PracticeCallUsage, PracticeUsage
from app.practice.pipeline import (
    PracticePorts,
    await_if_needed,
    generate_practice_artifact,
)
from app.rag.contracts import BudgetLimits, ExecutionContext
from app.rag.errors import ScopeRevoked
from app.rag.scope import require_execution_scope
from app.services import job_service, learning_concept_service, practice_service

logger = logging.getLogger(__name__)
_STAGES = ("llm", "embedding", "reranker", "search", "fetch", "images")


def _same_execution(job, current):
    # locked_job fences lease/attempt, but deliberately does not validate all
    # supplied request metadata. The practice publisher must do both.
    for field in (
        "task_id",
        "user_id",
        "kind",
        "operation",
        "mode",
        "request_hash",
        "request",
        "scope",
    ):
        if job.get(field) != current.get(field):
            raise not_found()


async def _authorize_execution(job, actor, *, conn=None):
    if conn is None:
        async with transaction() as tx:
            return await _authorize_execution(job, actor, conn=tx)
    current = await job_service.locked_job(job, conn)
    _same_execution(job, current)
    if (
        current["user_id"] != actor.owner_id
        or current["mode"] != "production"
        or current["kind"] != "practice_generate"
    ):
        raise ScopeRevoked("Practice publication requires its production owner")
    request = practice_service.generation_request(current["request"])
    from app.practice.grading_config import require_generation_types

    require_generation_types(request.spec.question_types)
    row, saved, scope = await practice_service.authorize_practice(
        conn,
        actor.owner_id,
        request.practice_id,
        job=current,
        generating=True,
        active=True,
    )
    return row, saved, scope


async def run_practice_generation(job, actor, engine, *, provider, usage_loader):
    """Run inside OwnerWorker's existing provider_meter.execution(job) context.

    ``usage_loader(owner_id, mode, logical_request_id) -> PracticeUsage`` is the
    explicit durable adapter also reusable by P04. Provider methods remain bound
    so the pure pipeline can inspect their actual prompt/model/output metadata.
    """
    _, request, scope = await _authorize_execution(job, actor)
    config = request.pipeline_config
    if (
        provider is None
        or getattr(provider, "output_token_limit", None) != config.output_token_reserve
        or getattr(provider, "prompt_hash", None) != request.prompt_hash
        or getattr(provider, "prompt_version", None) != config.prompt_version
    ):
        raise conflict(
            "practice_provider_configuration", "练习模型输出限额与固定配置不一致"
        )
    context = ExecutionContext(
        mode="production",
        run_id="rag_" + digest(job["task_id"])[:32],
        storage_namespace=scope.namespace,
        budget=BudgetLimits(
            max_llm_calls=5,
            max_reranker_calls=1,
            max_search_calls=0,
            max_fetch_calls=0,
            deadline_seconds=min(
                1800, max(0.001, (job["deadline_at"] - now()).total_seconds())
            ),
        ),
    )
    require_execution_scope(actor, context, scope)

    async def reauthorize(value):
        if value != scope:
            raise ScopeRevoked("Practice scope differs from the complete saved scope")
        _, pinned, current_scope = await _authorize_execution(job, actor)
        if pinned != request or current_scope != scope:
            raise ScopeRevoked("Practice source request has changed")
        return current_scope

    await job_service.heartbeat(job, "retrieving")
    artifact = await generate_practice_artifact(
        request.spec,
        actor,
        context,
        scope,
        PracticePorts(
            retrieve=engine.retrieve,
            generate=provider.generate,
            validate_semantics=provider.validate_semantics,
            reauthorize=reauthorize,
            verify_evidence=engine.verify_evidence,
            measure_input_tokens=provider.measure_input_tokens,
        ),
        config=config,
    )
    if (
        artifact.run_id != context.run_id
        or artifact.scope_fingerprint != scope.fingerprint
    ):
        raise ScopeRevoked("Practice artifact differs from its execution identity")
    durable = PracticeUsage.model_validate(
        await usage_loader(actor.owner_id, "production", request.generation_request_id)
    )
    usage = durable.model_dump(mode="json")
    # Keep pipeline timing (including real floating telemetry), while financial
    # values, call identities and token counters come only from durable rows.
    usage["stage_ms"] = {**artifact.usage.stage_ms, **durable.stage_ms}
    payload = artifact.model_dump(mode="json")
    payload["usage"] = usage
    artifact = PracticeArtifact.model_validate(payload)
    await job_service.heartbeat(job, "publishing")

    async def publish(current, result, conn):
        _same_execution(job, current)
        row, pinned, locked_scope = await _authorize_execution(
            current, actor, conn=conn
        )
        if pinned != request or locked_scope != scope:
            raise ScopeRevoked("Practice scope changed before publication")
        for item in artifact.evidence_pack.evidence:
            await await_if_needed(engine.verify_evidence(item, locked_scope))
        await practice_service.save_published_practice(conn, row, artifact)
        await learning_concept_service.bind_questions(
            conn,
            actor.owner_id,
            origin_kind="practice",
            origin_id=row["practice_id"],
            space_id=row["space_id"],
            scope_revision=row["scope_revision"],
            question_concepts=[
                QuestionConceptBinding(
                    question_id=q.id,
                    question_version=artifact.question_versions[q.id],
                    concept_ids=q.concept_ids,
                )
                for q in artifact.questions
            ],
        )
        # Only stable scalar identifiers go into the generic task result. The
        # service constructs the public DTO from the authorized stored artifact.
        result.update(practice_id=row["practice_id"], status="completed")

    await job_service.complete_job(job, {}, publisher=publish)


async def reconcile_practice_job(job, conn):
    """Terminal bookkeeping needs no source text and never revives an old task."""
    if conn is None:
        raise ValueError("Practice reconciliation requires an existing transaction")
    if job.get("kind") == "practice_grade":
        from app.workers.practice_grading_job import reconcile_practice_grading

        return await reconcile_practice_grading(job, conn)
    if job.get("kind") != "practice_generate" or job.get("mode") != "production":
        return
    if job.get("status") not in {"failed", "cancelled"}:
        return
    current = await practice_service.owned_practice_task(
        job["user_id"], job["task_id"], conn=conn, lock=True
    )
    if current["kind"] != "practice_generate" or current["status"] not in {
        "failed",
        "cancelled",
    }:
        return
    request = practice_service.generation_request(current["request"])
    preview = await fetch_one(
        "SELECT space_id FROM practice_sessions WHERE practice_id=%s AND owner_id=%s",
        (request.practice_id, current["user_id"]),
        conn=conn,
    )
    if preview is None:
        return
    await practice_service.lock_practice_space(
        conn, current["user_id"], preview["space_id"]
    )
    row = await practice_service.owned_practice(
        current["user_id"], request.practice_id, conn=conn, lock=True
    )
    if row["generation_task_id"] != current["task_id"] or row["status"] != "generating":
        return
    if row["artifact_json"] is not None or row["artifact_hash"] is not None:
        return
    saved, scope = practice_service._row_request_scope(row)
    practice_service.require_generation_job(current, row, saved, scope)
    await execute(
        "UPDATE practice_sessions SET status=%s,error_code=%s,revision=revision+1 "
        "WHERE practice_id=%s AND owner_id=%s AND generation_task_id=%s AND revision=%s "
        "AND status='generating' AND artifact_json IS NULL AND artifact_hash IS NULL",
        (
            current["status"],
            current["error_code"] or "cancelled",
            row["practice_id"],
            row["owner_id"],
            current["task_id"],
            row["revision"],
        ),
        conn=conn,
    )


def _amount(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _observed_count(value):
    return value if type(value) is int and value >= 0 else None


def _money(row, raw):
    """Use SQL DECIMAL settlement/ceilings, never recompute provider prices."""
    actual, reservation = None, None
    complete = True
    financial_row = row["cny_status"] is not None
    reported = _amount(raw.get("cost_cny"))
    quoted_reservation = _amount(raw.get("reserved_cost_cny"))
    if financial_row:
        reservation = _amount(row["cny_reserved"])
        if reservation is None:
            complete = False
        if (
            row["status"] == "completed"
            and raw.get("cost_status") == "estimated"
            and reported is not None
        ):
            if row["cny_status"] in {"settled", "released"}:
                actual = _amount(row["cny_actual"])
            if actual is None:
                complete = False
    else:
        # A known zero needs no positive budget reservation. Nonzero reported
        # charges without their financial journal cannot become known money.
        if quoted_reservation == 0:
            reservation = Decimal("0")
        if (
            row["status"] == "completed"
            and raw.get("cost_status") == "estimated"
            and reported == 0
        ):
            actual = Decimal("0")
        elif reported is not None and reported > 0:
            complete = False
        if quoted_reservation is not None and quoted_reservation > 0:
            complete = False
    outstanding = (
        reservation
        if financial_row and row["cny_status"] in {"reserved", "unknown"}
        else None
        if not financial_row and actual is None and quoted_reservation is None
        else Decimal("0")
    )
    return actual, reservation, outstanding, complete


async def load_practice_usage(
    owner_id: int, mode: str, logical_request_id: str
) -> PracticeUsage:
    """Project actual calls across every task/attempt for one saved logical ID.

    ``model`` and ``purpose`` stay in durable usage_json; frozen PracticeCallUsage
    permits neither. Missing historical attempt/model/purpose is never inferred
    from the current task. Unrepresentable rows retain real aggregate charges,
    reservations and diagnostics, but make the ledger incomplete and total null.
    Aggregate reserved_cost_cny means outstanding reserved/unknown money; each
    representable call also retains its original SQL DECIMAL reservation ceiling.
    """
    if (
        type(owner_id) is not int
        or owner_id <= 0
        or mode not in {"production", "evaluation"}
        or not logical_request_id
    ):
        raise ValueError(
            "An explicit owner, mode and logical practice identity are required"
        )
    async with transaction() as conn:
        tasks = await fetch_all(
            "SELECT j.task_id FROM quiz_tasks j WHERE j.user_id=%s AND j.mode=%s AND "
            "((j.kind='practice_generate' AND j.operation='practice.generate') OR "
            "(j.kind='practice_grade' AND j.operation='practice.grade') OR "
            "(j.kind='eval_sample' AND j.operation='eval.sample')) AND "
            "((j.kind='practice_generate' AND JSON_UNQUOTE(JSON_EXTRACT(j.request_json,'$.generation_request_id'))=%s) OR "
            "(j.kind IN ('practice_grade','eval_sample') AND JSON_UNQUOTE(JSON_EXTRACT(j.request_json,'$.grading_request_id'))=%s) OR "
            "EXISTS (SELECT 1 FROM provider_calls p WHERE p.owner_id=j.user_id AND CAST(p.mode AS BINARY)=CAST(j.mode AS BINARY) "
            "AND CAST(p.operation_id AS BINARY)=CAST(j.task_id AS BINARY) "
            "AND JSON_UNQUOTE(JSON_EXTRACT(p.usage_json,'$.logical_request_id'))=%s)) ORDER BY j.task_id",
            (
                owner_id,
                mode,
                logical_request_id,
                logical_request_id,
                logical_request_id,
            ),
            conn=conn,
        )
        if not tasks:
            return PracticeUsage()
        task_ids = [row["task_id"] for row in tasks]
        placeholders = ",".join(["%s"] * len(task_ids))
        rows = await fetch_all(
            "SELECT p.call_id,p.operation_id AS task_id,p.stage,p.status,p.usage_json,"
            "c.status AS call_status,c.reserved AS call_reserved,c.actual AS call_actual,"
            "m.status AS cny_status,m.reserved AS cny_reserved,m.actual AS cny_actual "
            "FROM provider_calls p LEFT JOIN budget_reservations c ON CAST(c.operation_id AS BINARY)=CAST(p.call_id AS BINARY) AND c.resource_type='calls' "
            "LEFT JOIN budget_reservations m ON CAST(m.operation_id AS BINARY)=CAST(p.call_id AS BINARY) AND m.resource_type='cny' "
            f"WHERE p.owner_id=%s AND p.mode=%s AND p.operation_id IN ({placeholders}) "
            "AND (JSON_EXTRACT(p.usage_json,'$.logical_request_id') IS NULL OR "
            "JSON_UNQUOTE(JSON_EXTRACT(p.usage_json,'$.logical_request_id'))=%s) "
            "ORDER BY p.created_at,p.call_id",
            (owner_id, mode, *task_ids, logical_request_id),
            conn=conn,
        )
        account_keys = [
            f"job:{task_id}:{stage}" for task_id in task_ids for stage in _STAGES
        ]
        key_placeholders = ",".join(["%s"] * len(account_keys))
        accounts = await fetch_all(
            f"SELECT account_key,used,reserved FROM budget_accounts WHERE resource_type='calls' AND account_key IN ({key_placeholders})",
            tuple(account_keys),
            conn=conn,
        )
    calls, counters, stage_ms = [], dict.fromkeys(_STAGES, 0), {}
    complete, all_known, tokens_complete, reservations_known = True, True, True, True
    known, reserved = Decimal("0"), Decimal("0")
    inputs = outputs = embeddings = 0
    expected_accounts = dict.fromkeys(account_keys, 0)
    for row in rows:
        raw = load(row["usage_json"])
        if not isinstance(raw, dict):
            raw = {}
            complete = False
        stage, status = row["stage"], row["status"]
        if stage in counters:
            counters[stage] += 1
            expected_accounts[f"job:{row['task_id']}:{stage}"] += 1
        else:
            complete = False
        if stage == "llm" and raw.get("purpose") == "reranker":
            counters["reranker"] += 1
            expected_accounts[f"job:{row['task_id']}:reranker"] += 1
        if stage == "llm" and any(
            not isinstance(raw.get(field), str) or not raw[field]
            for field in ("model", "purpose")
        ):
            complete = False
            logger.warning(
                "Practice usage metadata missing call_id=%s task_id=%s",
                row["call_id"],
                row["task_id"],
            )
        if (
            row["call_status"] != "settled"
            or _amount(row["call_reserved"]) != 1
            or _amount(row["call_actual"]) != 1
        ):
            complete = False
        actual, ceiling, outstanding, financial_complete = _money(row, raw)
        complete = complete and financial_complete
        if actual is not None:
            known += actual
        else:
            all_known = False
        if outstanding is None:
            reservations_known = False
        else:
            reserved += outstanding
        attempt = raw.get("attempt")
        identity_valid = (
            type(attempt) is int
            and attempt >= 1
            and stage in _STAGES
            and status in {"reserved", "completed", "unknown"}
            and raw.get("call_id", row["call_id"]) == row["call_id"]
            and raw.get("stage", stage) == stage
            and raw.get("status", status) == status
        )
        if identity_valid:
            calls.append(
                PracticeCallUsage(
                    call_id=row["call_id"],
                    task_id=row["task_id"],
                    attempt=attempt,
                    stage=stage,
                    status=status,
                    cost_cny=actual,
                    reserved_cost_cny=ceiling,
                    cost_status="estimated" if actual is not None else "unknown",
                )
            )
        else:
            complete = False
            logger.warning(
                "Practice usage identity incomplete call_id=%s task_id=%s",
                row["call_id"],
                row["task_id"],
            )
        if stage in {"llm", "embedding"}:
            input_count, output_count = (
                _observed_count(raw.get("input_tokens")),
                _observed_count(raw.get("output_tokens")),
            )
            if input_count is None or output_count is None:
                tokens_complete = False
            if stage == "embedding":
                embeddings += input_count or 0
            else:
                inputs += input_count or 0
                outputs += output_count or 0
        elapsed = raw.get("latency_ms")
        if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
            stage_ms[f"provider_{stage}"] = (
                stage_ms.get(f"provider_{stage}", 0) + elapsed
            )
    saved_accounts = {row["account_key"]: row for row in accounts}
    for key, expected in expected_accounts.items():
        saved = saved_accounts.get(key)
        if saved is None:
            if expected:
                complete = False
        elif _amount(saved["used"]) != expected or _amount(saved["reserved"]) != 0:
            complete = False
    return PracticeUsage(
        calls=calls,
        ledger_complete=complete,
        llm_calls=counters["llm"],
        embedding_calls=counters["embedding"],
        reranker_calls=counters["reranker"],
        search_calls=counters["search"],
        fetch_calls=counters["fetch"],
        input_tokens=inputs,
        output_tokens=outputs,
        embedding_tokens=embeddings,
        token_count_method="durable-provider-reported-v1"
        if tokens_complete
        else "durable-provider-reported-partial-v1",
        stage_ms=stage_ms,
        cost_cny=known if complete and all_known else None,
        known_cost_cny=known,
        reserved_cost_cny=reserved if reservations_known else None,
        cost_status_cny="estimated"
        if complete and all_known
        else "unknown"
        if rows or not complete
        else "unreported",
    )
