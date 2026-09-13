"""Single Chroma owner: serial jobs, renewable leases and fenced publication.

Only managed heartbeat/dispatch tasks are created here. Business requests are
stored in MySQL first; a process restart claims the same durable job identity.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import time
from datetime import timedelta

from app.core.config import get_settings
from app.core.db import (
    close_mysql_pool,
    execute,
    fetch_all,
    fetch_one,
    init_pool,
    transaction,
)
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load, now, uid
from app.models.learning import ReportText
from app.rag.budget import BudgetLedger
from app.rag.contracts import (
    ActorContext,
    BudgetLimits,
    ExecutionContext,
    PipelineConfig,
    ResolvedScope,
)
from app.rag.errors import (
    GenerationValidationFailed,
    InsufficientEvidence,
    RagError,
    ScopeRevoked,
)
from app.rag.evaluation import run_eval_sample
from app.rag.evaluation_artifacts import (
    AnswerGradingEvalArtifact,
    LearningEvaluationUsage,
    PracticeGenerationEvalArtifact,
)
from app.rag.scope import require_execution_scope
from app.services import (
    job_service,
    learning_quiz_service,
    learning_service,
    quiz_service,
    source_service,
)
from app.services.provider_meter import execution

logger = logging.getLogger(__name__)


def _remaining(job):
    return max(0.001, (job["deadline_at"] - now()).total_seconds())


def _run_id(job):
    return "rag_" + digest(job["task_id"])[:32]


def _attempt_directory(job, root="rag/runs"):
    return f"{root}/{_run_id(job)}/{job['attempt']}-{digest(job['lease_token'])[:16]}"


def _error_code(exc):
    if isinstance(exc, (RagError, AppError)):
        return exc.code
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "deadline_exceeded"
    return "worker_execution_failed"


async def _actor(job):
    user = await fetch_one("SELECT id,role FROM users WHERE id=%s", (job["user_id"],))
    if not user:
        raise not_found()
    actor = ActorContext(owner_id=user["id"], roles=[user["role"]])
    if (
        job["mode"] == "evaluation"
        and job["kind"] != "delete"
        and "evaluator" not in actor.roles
    ):
        raise ScopeRevoked("Evaluation permission is no longer available")
    return actor


def _scope(job):
    return (
        ResolvedScope.model_validate(job["scope"])
        if job.get("scope")
        else ResolvedScope(
            owner_id=job["user_id"],
            namespace="production"
            if job["mode"] == "production"
            else f"evaluation:{job['user_id']}",
        )
    )


async def _metered_usage(job, usage):
    """Include every persisted attempt, including unknown failures and retries."""
    rows = await fetch_all(
        "SELECT call_id,stage,status,usage_json FROM provider_calls WHERE operation_id=%s ORDER BY created_at,call_id",
        (job["task_id"],),
    )
    calls = [
        {
            **load(row["usage_json"], {}),
            "call_id": row["call_id"],
            "stage": row["stage"],
            "status": row["status"],
        }
        for row in rows
    ]
    result = dict(usage)
    counters = {
        "llm": "llm_calls",
        "embedding": "embedding_calls",
        "reranker": "reranker_calls",
        "search": "search_calls",
        "fetch": "fetch_calls",
    }
    for stage, field in counters.items():
        if any(call["stage"] == stage for call in calls):
            result[field] = sum(call["stage"] == stage for call in calls)
    chat_rankings = sum(
        call["stage"] == "llm" and call.get("purpose") == "reranker" for call in calls
    )
    if chat_rankings:
        result["reranker_calls"] = (
            sum(call["stage"] == "reranker" for call in calls) + chat_rankings
        )
    # A chat ranking has one durable provider record and consumes both quotas.
    observed_count = (
        sum(int(result.get(field, 0)) for field in counters.values()) - chat_rankings
    )
    result["calls"] = calls
    result["ledger_complete"] = len(calls) >= observed_count
    return result


async def _learning_evaluation_usage(job, usage):
    """Seal one logical request's complete ledger, including replacement tasks.

    Reuse the production settlement reader for SQL DECIMAL costs and journal
    consistency. Only the outer evaluation contains provider metadata and totals.
    """
    from app.workers.practice_job import load_practice_usage

    request = job["request"]
    field = (
        "grading_request_id"
        if request.get("grading_request_id")
        else "generation_request_id"
    )
    logical_id = request.get(field)
    if not isinstance(logical_id, str) or not 1 <= len(logical_id) <= 64:
        raise ScopeRevoked("Evaluation logical request identity is unavailable")
    tasks = await fetch_all(
        "SELECT task_id,created_at FROM quiz_tasks WHERE user_id=%s AND mode='evaluation' "
        "AND kind='eval_sample' AND operation='eval.sample' "
        f"AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.{field}'))=%s "
        "AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.run_id'))=%s "
        "AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.result_id'))=%s ORDER BY created_at,task_id",
        (job["user_id"], logical_id, request["run_id"], request["result_id"]),
    )
    if job["task_id"] not in {task["task_id"] for task in tasks}:
        raise ScopeRevoked("Evaluation logical request no longer matches the task")
    task_ids = [task["task_id"] for task in tasks]
    placeholders = ",".join(["%s"] * len(task_ids))
    rows = await fetch_all(
        "SELECT call_id,operation_id AS task_id,stage,status,usage_json FROM provider_calls "
        f"WHERE owner_id=%s AND mode='evaluation' AND operation_id IN ({placeholders}) "
        "ORDER BY created_at,call_id",
        (job["user_id"], *task_ids),
    )
    durable = await load_practice_usage(job["user_id"], "evaluation", logical_id)
    data = durable.model_dump(mode="json")
    by_id = {call.call_id: call.model_dump(mode="json") for call in durable.calls}
    if not rows and not durable.calls:
        # A rule grade or a failure before generation can legitimately have no
        # provider row. Check the call accounts before certifying a known zero.
        accounts = await fetch_all(
            "SELECT used,reserved FROM budget_accounts WHERE resource_type='calls' "
            + "AND ("
            + " OR ".join(["account_key LIKE %s"] * len(task_ids))
            + ")",
            tuple(f"job:{task_id}:%" for task_id in task_ids),
        )
        empty = all(row["used"] == 0 and row["reserved"] == 0 for row in accounts)
        data.update(
            ledger_complete=empty,
            cost_cny="0" if empty else None,
            known_cost_cny="0",
            reserved_cost_cny="0" if empty else None,
            cost_status_cny="estimated" if empty else "unknown",
        )
    elif set(by_id) != {row["call_id"] for row in rows}:
        data.update(ledger_complete=False, cost_cny=None, cost_status_cny="unknown")
    calls = []
    for row in rows:
        raw = load(row["usage_json"], {})
        if not isinstance(raw, dict):
            raw = {}
        saved = by_id.get(row["call_id"], {})
        calls.append(
            {
                **raw,
                **saved,
                "call_id": row["call_id"],
                "task_id": row["task_id"],
                "stage": row["stage"],
                "status": row["status"],
                "cost_cny": saved.get("cost_cny"),
                "reserved_cost_cny": saved.get("reserved_cost_cny"),
                "cost_status": saved.get("cost_status", "unknown"),
            }
        )
    data["calls"] = calls
    data["unknown_call_count"] = sum(call["cost_cny"] is None for call in calls)
    data["unknown_reserved_cost_cny"] = data["reserved_cost_cny"]
    data["stage_ms"] = {**usage.get("stage_ms", {}), **data["stage_ms"]}
    if tasks[0].get("created_at") is not None:
        data["stage_ms"]["end_to_end"] = (
            now() - tasks[0]["created_at"]
        ).total_seconds() * 1000
    return LearningEvaluationUsage.model_validate(data).model_dump(mode="json")


def _missing_evaluation_provider(*args, **kwargs):
    raise GenerationValidationFailed("Evaluation provider is unavailable")


class OwnerWorker:
    def __init__(
        self,
        engine,
        *,
        report_generator=None,
        practice_provider=None,
        grading_provider=None,
        course_generator=None,
        course_tutor_generator=None,
        course_application_generator=None,
        worker_id=None,
        role=None,
    ):
        self.engine = engine
        self.report_generator = report_generator
        self.practice_provider = practice_provider
        self.grading_provider = grading_provider
        self.course_generator = course_generator
        self.course_tutor_generator = course_tutor_generator
        self.course_application_generator = course_application_generator
        from app.workers.roles import claim_kinds, effective_role
        self.role = effective_role(get_settings(), role)
        self.kinds = claim_kinds(self.role)
        self.worker_id = worker_id or uid(self.role)
        self._serial = asyncio.Lock()
        self._next_course_review_reconcile = 0.0
        self._next_event_purge = 0.0

    async def _worker_heartbeat(self):
        teaching_ready = self.course_generator is not None and getattr(self.course_generator, "reviewer", None) is not None
        if self.role != "owner":
            available = await self.engine.store.projection.healthcheck()
            await execute(
                "INSERT INTO worker_heartbeats(worker_id,role,heartbeat_at,status_json) VALUES(%s,%s,UTC_TIMESTAMP(6),%s) "
                "ON DUPLICATE KEY UPDATE heartbeat_at=UTC_TIMESTAMP(6),role=VALUES(role),status_json=VALUES(status_json)",
                (self.worker_id, "rag_" + self.role, dump({"vector_backend": "qdrant", "vector_available": available,
                    "teaching_agents_ready": teaching_ready})),
            )
            return
        await execute(
            "INSERT INTO worker_heartbeats(worker_id,role,heartbeat_at,status_json) VALUES(%s,'rag_owner',UTC_TIMESTAMP(6),%s) "
            "ON DUPLICATE KEY UPDATE heartbeat_at=UTC_TIMESTAMP(6),role='rag_owner',status_json=VALUES(status_json)",
            (self.worker_id, dump({"teaching_agents_ready": teaching_ready})),
        )

    async def _monitor(self, job, task, lease_lost):
        interval = max(
            0.1,
            min(
                get_settings().job_heartbeat_seconds,
                get_settings().job_lease_seconds / 3,
            ),
        )
        while True:
            await asyncio.sleep(interval)
            try:
                await job_service.heartbeat(job)
                await self._worker_heartbeat()
            except Exception:  # noqa: BLE001 - Losing the DB lease must stop in-flight providers.
                lease_lost.set()
                task.cancel()
                return

    async def run_once(self, *, task_id=None):
        """Return True when a durable job was claimed, even if it ends in failure."""
        async with self._serial:
            from app.services import vector_projection_service as projections

            if projections.enabled():
                try:
                    await projections.assert_not_maintenance()
                except AppError as exc:
                    if exc.code == "vector_maintenance":
                        return False
                    raise
            await self._worker_heartbeat()
            if self.role != "generation" and time.monotonic() >= self._next_course_review_reconcile:
                from app.services.course_review_service import reconcile_course_reviews

                try:
                    await reconcile_course_reviews(limit=100)
                except Exception:  # Scheduling is retried from the durable settlement events.
                    logger.exception("Course review scheduling will retry")
                self._next_course_review_reconcile = time.monotonic() + 5
            if self.role != "generation" and time.monotonic() >= self._next_event_purge:
                from app.services import task_event_service

                self._next_event_purge = time.monotonic() + 300
                try:
                    await task_event_service.purge_expired_events()
                    from app.services.content_event_service import purge_content
                    from app.services.experience_event_service import purge_experience_events
                    from app.services.teaching_quality_service import purge_expired_quality_candidates

                    await purge_content()
                    await purge_experience_events()
                    await purge_expired_quality_candidates()
                except Exception:  # noqa: BLE001 - 清理失败下一周期重试
                    logger.exception("Task event purge will retry")
            await self.reconcile(task_id=task_id)
            try:
                job = await job_service.claim_job(
                    self.worker_id, task_id=task_id, kinds=self.kinds, maintain=self.role != "generation"
                )
            except AppError as exc:
                if exc.code == "vector_maintenance":
                    return False
                raise
            if job is None:
                await self.reconcile(task_id=task_id)
                return False
            lease_lost = asyncio.Event()
            task = asyncio.create_task(self._execute(job), name=f"job:{job['task_id']}")
            heartbeat = asyncio.create_task(
                self._monitor(job, task, lease_lost), name=f"lease:{job['task_id']}"
            )
            try:
                await asyncio.wait_for(task, timeout=_remaining(job))
            except asyncio.CancelledError:
                if not lease_lost.is_set():
                    await self._fail(job, "worker_stopped", retryable=True)
                    raise
            except Exception as exc:  # noqa: BLE001 - Persist a redacted terminal job failure.
                code = _error_code(exc)
                logger.warning("Durable job failed kind=%s code=%s", job["kind"], code)
                await self._fail(job, code, retryable=False)
            finally:
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
                if not task.done():
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                await self.reconcile(task_id=job["task_id"])
            return True

    async def _fail(self, job, code, *, retryable=False):
        try:
            await job_service.fail_job(job, code, retryable=retryable)
        except AppError as exc:
            if exc.code != "stale_lease":
                raise

    async def _execute(self, job):
        from app.services.vector_projection_service import execution_receipt
        from app.services.content_event_service import content_preview

        async with execution_receipt(job, self.worker_id):
            async with content_preview(job):
                await self._execute_managed(job)

    async def _execute_managed(self, job):
        # The ContextVar propagates into the provider adapters and the managed
        # LangGraph tasks, so no production/evaluation charge can cross jobs.
        with execution(job):
            actor = await _actor(job)
            if job["kind"] == "ingest":
                await job_service.heartbeat(job, "parsing_indexing")
                request = await source_service.build_request(job)
                budget = BudgetLedger(
                    BudgetLimits(
                        max_embedding_calls=1000,
                        max_input_tokens=32 * 1024 * 1024,
                        deadline_seconds=min(1800, _remaining(job)),
                    )
                )
                result = await self.engine.build(request, budget=budget)
                await source_service.publish_build(job, result)
            elif job["kind"] == "quiz":
                await self._quiz(job, actor)
            elif job["kind"] == "practice_generate":
                from app.workers.practice_job import (
                    load_practice_usage,
                    run_practice_generation,
                )

                await run_practice_generation(
                    job,
                    actor,
                    self.engine,
                    provider=self.practice_provider,
                    usage_loader=load_practice_usage,
                )
            elif job["kind"] == "practice_grade":
                from app.workers.practice_grading_job import run_practice_grading
                from app.workers.practice_job import load_practice_usage

                await run_practice_grading(
                    job,
                    actor,
                    self.engine,
                    provider=self.grading_provider,
                    usage_loader=load_practice_usage,
                )
            elif job["kind"] == "qa":
                from app.workers.qa_job import run_qa

                await run_qa(job, actor, self.engine, usage_loader=_metered_usage)
            elif job["kind"] in {"course_outline", "course_lesson"}:
                from app.workers.course_job import run_course

                def record_teaching_summary(summary):
                    self.engine.store.put_json(
                        _attempt_directory(job) + "/graph-summary.json",
                        summary.model_dump(mode="json"),
                    )

                await run_course(
                    job, self.engine, self.course_generator,
                    usage_loader=_metered_usage, record_summary=record_teaching_summary,
                )
            elif job["kind"] == "course_tutor":
                from app.workers.course_tutor_job import run_course_tutor

                await run_course_tutor(
                    job, actor, self.engine, generator=self.course_tutor_generator,
                    usage_loader=_metered_usage,
                )
            elif job["kind"] in {"course_application_generate", "course_application_feedback"}:
                from app.workers.course_application_job import run_course_application

                await run_course_application(
                    job, actor, self.engine, generator=self.course_application_generator,
                    usage_loader=_metered_usage,
                )
            elif job["kind"] == "report":
                await self._report(job, actor)
            elif job["kind"] == "learning_project":
                from app.workers.learning_projection_job import run_learning_projection

                await run_learning_projection(job)
            elif job["kind"] == "delete":
                await job_service.heartbeat(job, "removing_artifacts")
                await source_service.cleanup_document(
                    actor.owner_id, job["request"]["doc_id"], self.engine.store
                )
                await job_service.complete_job(
                    job, {"doc_id": job["request"]["doc_id"], "status": "deleted"}
                )
            elif job["kind"] == "eval_sample":
                await self._evaluation(job, actor)
            elif job["kind"] == "images":
                if job["mode"] != "production":
                    raise ScopeRevoked("Evaluation cannot create learning images")
                from app.services.image_job_service import run_images

                await run_images(job)
            else:
                raise AppError(422, "unsupported_job", "任务类型不受支持")

    async def _quiz(self, job, actor):
        if job["mode"] != "production":
            raise ScopeRevoked("Evaluation cannot create a learning session")
        from app.services.evaluation_service import pipeline_config
        from app.services import course_quiz_service

        async with transaction() as conn:
            current = await job_service.locked_job(job, conn)
            await course_quiz_service.authorize_job(actor.owner_id, current, conn=conn)

        scope = _scope(job)
        context = ExecutionContext(
            mode="production",
            run_id=_run_id(job),
            storage_namespace=scope.namespace,
            budget=BudgetLimits(deadline_seconds=min(1800, _remaining(job))),
        )
        require_execution_scope(actor, context, scope)
        config = pipeline_config(
            job["request"].get("pipeline_id", get_settings().rag_pipeline_id)
        )
        if config.pipeline_version == "legacy-summary-b0":
            raise ScopeRevoked("Historical B0 is evaluation only")
        spec, learning_context = quiz_service.parse_quiz_request(job["request"])
        if learning_context is not None:
            spec, scope, learning_context = await learning_quiz_service.authorize_job(
                actor.owner_id, job
            )
        await job_service.heartbeat(job, "retrieving_generating")
        coverage_options = (
            {"coverage_plan": learning_context.coverage_plan}
            if learning_context is not None
            else {}
        )
        graph_summary = {}
        directory = _attempt_directory(job)

        def record_graph_summary(summary):
            graph_summary.update(summary.model_dump(mode="json"))
            self.engine.store.put_json(directory + "/graph-summary.json", graph_summary)

        artifact = await self.engine.generate(
            spec, actor, context, scope, config, record_summary=record_graph_summary, **coverage_options
        )
        payload = artifact.model_dump(mode="json")
        payload["usage"] = await _metered_usage(job, payload["usage"])
        directory = _attempt_directory(job)
        evidence_key = self.engine.store.put_json(directory + "/artifact.json", payload)
        debug = {
            "graph_summary": graph_summary,
            "trace": artifact.trace,
            "usage": payload["usage"],
            "validation": artifact.validation.model_dump(mode="json"),
            "effective_config": artifact.effective_config,
        }
        debug_key = self.engine.store.put_json(directory + "/debug.json", debug)
        result = {}

        async def publish(current, public, conn):
            await course_quiz_service.authorize_job(actor.owner_id, current, conn=conn)
            if learning_context is not None:
                (
                    saved_spec,
                    saved_scope,
                    saved_context,
                ) = await learning_quiz_service.authorize_job(
                    actor.owner_id, current, conn=conn, lock_concepts=False
                )
                if (
                    saved_spec != spec
                    or saved_scope != scope
                    or saved_context != learning_context
                ):
                    raise conflict(
                        "learning_request_changed", "练习请求与生成时的学习上下文不一致"
                    )
            else:
                await source_service.reauthorize_scope(scope, conn=conn)
            manifest = {
                "resolved_scope": scope.model_dump(mode="json"),
                "pipeline": config.model_dump(mode="json"),
                "origin_task_id": current["task_id"],
                "attempt": current["attempt"],
            }
            await execute(
                "INSERT INTO rag_runs(run_id,owner_id,mode,namespace,pipeline_hash,manifest_json,status,"
                "evidence_artifact_key,evidence_hash,debug_artifact_key,debug_hash,debug_expires_at,usage_json) "
                "VALUES(%s,%s,'production',%s,%s,%s,'completed',%s,%s,%s,%s,%s,%s)",
                (
                    context.run_id,
                    actor.owner_id,
                    scope.namespace,
                    artifact.pipeline_config_hash,
                    dump(manifest),
                    evidence_key,
                    digest(dump(payload)),
                    debug_key,
                    digest(dump(debug)),
                    now() + timedelta(days=get_settings().debug_retention_days),
                    dump(payload["usage"]),
                ),
                conn=conn,
            )
            images = bool(current["request"].get("generate_images"))
            questions = [
                {
                    **question.model_dump(mode="json"),
                    "image_status": "pending" if images else "not_requested",
                }
                for question in artifact.questions
            ]
            await execute(
                "INSERT INTO quiz_sessions(quiz_id,user_id,title,summary,user_input,questions_json,rag_run_id,"
                "source_scope_json,source_policy,source_status,origin_task_id,images_status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    current["quiz_id"],
                    actor.owner_id,
                    artifact.title,
                    artifact.summary,
                    spec.user_input,
                    dump(questions),
                    context.run_id,
                    dump(scope),
                    spec.source_policy,
                    artifact.source_status,
                    current["task_id"],
                    "pending" if images else "not_requested",
                ),
                conn=conn,
            )
            from app.services.course_assessment_service import publish_assessment_quiz

            await publish_assessment_quiz(conn, actor.owner_id, current, artifact)
            if images:
                await job_service.enqueue_job(
                    actor.owner_id,
                    "images",
                    {"quiz_id": current["quiz_id"]},
                    "images:" + current["quiz_id"],
                    scope=scope.model_dump(mode="json"),
                    conn=conn,
                )
            public.update(
                await learning_service.get_detail(
                    actor.owner_id, current["quiz_id"], conn=conn
                )
            )
            if learning_context is not None:
                await learning_quiz_service.publish_context(
                    conn,
                    actor.owner_id,
                    current["quiz_id"],
                    spec,
                    scope,
                    learning_context,
                    artifact,
                )

        await job_service.complete_job(job, result, publisher=publish)

    async def _report(self, job, actor):
        if job["mode"] != "production":
            raise ScopeRevoked("Evaluation cannot create learning reports")
        quiz_id = job["request"]["quiz_id"]
        async with transaction() as conn:
            await job_service.locked_job(job, conn)
            quiz = await learning_service.owned_quiz(
                actor.owner_id, quiz_id, conn=conn, lock=True
            )
            scores = await fetch_one(
                "SELECT * FROM answer_records WHERE quiz_id=%s AND user_id=%s",
                (quiz_id, actor.owner_id),
                conn=conn,
            )
            report = await fetch_one(
                "SELECT * FROM reports WHERE quiz_id=%s AND user_id=%s FOR UPDATE",
                (quiz_id, actor.owner_id),
                conn=conn,
            )
            if (
                not scores
                or not report
                or quiz["status"] != "settled"
                or report["stats_revision"] != job["request"]["stats_revision"]
            ):
                raise conflict("report_snapshot_changed", "学习结算快照无效")
            await execute(
                "UPDATE reports SET status='running',error_code=NULL WHERE quiz_id=%s",
                (quiz_id,),
                conn=conn,
            )
        if self.report_generator is None:
            raise AppError(503, "report_provider_unavailable", "学习报告模型未配置")
        await job_service.heartbeat(job, "writing_report")
        summary = {
            "total_questions": scores["total_questions"],
            "correct_count": scores["correct_count"],
            "accuracy": float(scores["accuracy"]),
            "xp_awarded": quiz["xp_awarded"],
        }
        generated = await self.report_generator(
            topic=quiz["user_input"] or quiz["title"],
            questions=load(quiz["questions_json"]),
            answer_records=load(scores["records_json"]),
            score_summary=summary,
        )
        text = ReportText.model_validate(
            generated.model_dump(mode="json")
            if hasattr(generated, "model_dump")
            else generated
        )

        async def publish(current, result, conn):
            row = await fetch_one(
                "SELECT stats_revision FROM reports WHERE quiz_id=%s AND user_id=%s FOR UPDATE",
                (quiz_id, actor.owner_id),
                conn=conn,
            )
            if not row or row["stats_revision"] != current["request"]["stats_revision"]:
                raise conflict("report_snapshot_changed", "学习结算快照已变化")
            await execute(
                "UPDATE reports SET report_json=%s,status='completed',error_code=NULL WHERE quiz_id=%s AND user_id=%s",
                (dump(text), quiz_id, actor.owner_id),
                conn=conn,
            )

        await job_service.complete_job(
            job, {"quiz_id": quiz_id, "report_status": "completed"}, publisher=publish
        )

    async def _evaluation_context(self, job, conn):
        # Reuse the same source -> dataset -> run -> result lock ordering as the
        # independent scorer. The outer publication already owns this job row.
        from app.services.evaluation_scoring import _locked_context

        evaluator = await fetch_one(
            "SELECT role FROM users WHERE id=%s FOR SHARE", (job["user_id"],), conn=conn
        )
        if not evaluator or evaluator["role"] != "evaluator":
            raise ScopeRevoked("Evaluation permission is no longer available")
        prepared = await _locked_context(job["request"]["result_id"], conn)
        if prepared is None:
            raise conflict("evaluation_busy", "评测结果正由其他进程处理")
        result, run, _, sample = prepared
        if (
            run["owner_id"] != job["user_id"]
            or run["run_id"] != job["request"]["run_id"]
        ):
            raise ScopeRevoked("Evaluation job identity does not match its run")
        manifest = load(run["manifest_json"])
        if dump(manifest.get("source_scopes", {}).get(result["sample_id"])) != dump(
            job["scope"]
        ):
            raise ScopeRevoked("Evaluation source pin differs from its frozen run")
        return result, run, sample, manifest

    async def _evaluation(self, job, actor):
        from app.practice.pipeline import PracticePorts
        from app.practice.short_answer import GradingPorts
        from app.services.evaluation_service import require_provider_configuration

        started, started_at = time.perf_counter(), now()
        if job["mode"] != "evaluation":
            raise ScopeRevoked("Evaluation jobs require isolated execution")
        async with transaction() as conn:
            await job_service.locked_job(job, conn)
            row, run, sample, manifest = await self._evaluation_context(job, conn)
            require_provider_configuration(manifest)
            if row["status"] not in {"queued", "running"}:
                raise conflict("prediction_already_published", "此样本的预测已经发布")
            await execute(
                "UPDATE eval_results SET status='running',prediction_status='running' WHERE result_id=%s",
                (row["result_id"],),
                conn=conn,
            )
            await execute(
                "UPDATE eval_runs SET status='running' WHERE run_id=%s",
                (run["run_id"],),
                conn=conn,
            )
        scope = _scope(job)
        learning_case = sample["case_type"] in {"practice_generation", "answer_grading"}
        context = ExecutionContext(
            mode="evaluation",
            run_id=run["run_id"] if learning_case else _run_id(job),
            storage_namespace=scope.namespace,
            budget=BudgetLimits(deadline_seconds=min(1800, _remaining(job))),
        )
        pinned = manifest.get("case_pipeline_configs", {}).get(sample["case_type"], {})
        config = PipelineConfig.model_validate(
            pinned.get("config", manifest["pipeline_config"])
        )
        if config.pipeline_config_hash != pinned.get(
            "hash", manifest["pipeline_config_hash"]
        ):
            raise conflict("pipeline_checksum_mismatch", "评测方案校验和不一致")

        async def reauthorize_evaluation(value):
            if value.fingerprint != scope.fingerprint:
                raise ScopeRevoked("Evaluation source scope changed during execution")
            async with transaction() as conn:
                current = await job_service.locked_job(job, conn)
                if (
                    current["request"] != job["request"]
                    or current["scope"] != job["scope"]
                ):
                    raise ScopeRevoked("Evaluation task changed during execution")
                active, _, _, frozen = await self._evaluation_context(current, conn)
                if active["status"] not in {"queued", "running"}:
                    raise ScopeRevoked("Evaluation prediction is no longer active")
                require_provider_configuration(frozen)
            return value

        ports = {}
        if learning_case:
            if sample["case_type"] == "practice_generation" and self.practice_provider:
                ports["practice_ports"] = PracticePorts(
                    retrieve=self.engine.retrieve,
                    generate=self.practice_provider.generate,
                    validate_semantics=self.practice_provider.validate_semantics,
                    reauthorize=reauthorize_evaluation,
                    verify_evidence=self.engine.verify_evidence,
                    measure_input_tokens=self.practice_provider.measure_input_tokens,
                )
            if sample["case_type"] == "answer_grading":
                # Rules use the same authorization port without a configured model.
                ports["grading_ports"] = GradingPorts(
                    grade=getattr(
                        self.grading_provider, "grade", _missing_evaluation_provider
                    ),
                    reauthorize=reauthorize_evaluation,
                    verify_evidence=self.engine.verify_evidence,
                    measure_input_tokens=getattr(
                        self.grading_provider,
                        "measure_input_tokens",
                        _missing_evaluation_provider,
                    ),
                )
                ports["grading_request_id"] = job["request"].get("grading_request_id")
        status, code = "completed", None
        try:
            artifact = await run_eval_sample(
                sample, actor, context, self.engine, scope, config, **ports
            )
            payload = artifact.model_dump(mode="json")
            status, code = payload.get("status", "completed"), payload.get("error_code")
        except Exception as exc:  # noqa: BLE001 - Publish redacted wrappers for new case failures.
            if not learning_case and not isinstance(exc, (RagError, AppError)):
                raise
            if (
                isinstance(exc, ScopeRevoked)
                or isinstance(exc, AppError)
                and (
                    exc.status in {401, 403, 404}
                    or exc.code
                    in {
                        "stale_lease",
                        "run_stopped",
                        "source_revoked",
                        "dataset_revoked",
                        "raw_artifacts_expired",
                        "evaluation_identity_changed",
                    }
                )
            ):
                raise
            code = _error_code(exc)
            status = (
                "refused"
                if isinstance(exc, InsufficientEvidence)
                and sample["case_type"] in {"quiz", "practice_generation"}
                else "timeout"
                if learning_case
                and (isinstance(exc, TimeoutError) or code == "deadline_exceeded")
                else "failed"
            )
            if learning_case:
                wrapper = (
                    PracticeGenerationEvalArtifact
                    if sample["case_type"] == "practice_generation"
                    else AnswerGradingEvalArtifact
                )
                payload = wrapper(
                    run_id=context.run_id,
                    sample_id=sample["sample_id"],
                    status=status,
                    error_code=code,
                ).model_dump(mode="json")
            else:
                payload = {
                    "case_type": sample["case_type"],
                    "schema_version": "1",
                    "run_id": context.run_id,
                    "status": status,
                    "error_code": code,
                    "evidence": [],
                    "usage": getattr(exc, "details", {}).get("usage", {}),
                }
                if sample["case_type"] == "quiz":
                    payload.update(questions=[], refusal_reason=code)
        payload.update(
            sample_id=row["sample_id"], repeat_index=row["repeat_index"], status=status
        )
        if learning_case:
            usage = payload.setdefault("usage", {})
            stages = usage.setdefault("stage_ms", {})
            stages["execution"] = (time.perf_counter() - started) * 1000
            if sample["case_type"] == "answer_grading":
                stages.setdefault("grading", stages["execution"])
            if job["attempt"] == 1 and job.get("created_at") is not None:
                stages["queue"] = (
                    started_at - job["created_at"]
                ).total_seconds() * 1000
            payload["usage"] = await _learning_evaluation_usage(job, usage)
            wrapper = (
                PracticeGenerationEvalArtifact
                if sample["case_type"] == "practice_generation"
                else AnswerGradingEvalArtifact
            )
            payload = wrapper.model_validate(payload).model_dump(mode="json")
        else:
            payload["usage"] = await _metered_usage(job, payload.get("usage", {}))
        key = self.engine.store.put_json(
            _attempt_directory(job, "evaluation/artifacts") + "/prediction.json",
            payload,
        )

        async def publish(current, result, conn):
            if current["request"] != job["request"] or current["scope"] != job["scope"]:
                raise ScopeRevoked("Evaluation task changed before publication")
            current_row, _, current_sample, _ = await self._evaluation_context(
                current, conn
            )
            if (
                current_row["status"] not in {"queued", "running"}
                or current_sample["sample_id"] != sample["sample_id"]
            ):
                raise conflict("prediction_already_published", "此样本的预测已经发布")
            attempts = load(current_row["attempts_json"], [])
            attempts.append(
                {
                    "event": "prediction_published",
                    "attempt": current["attempt"],
                    "at": iso(now()),
                    "prediction_status": status,
                    "artifact_hash": digest(dump(payload)),
                }
            )
            await execute(
                "UPDATE eval_results SET artifact_json=%s,artifact_key=%s,prediction_status=%s,status='pending_scoring',"
                "error_code=%s,attempts_json=%s WHERE result_id=%s",
                (dump(payload), key, status, code, dump(attempts), row["result_id"]),
                conn=conn,
            )

        await job_service.complete_job(
            job,
            {"result_id": row["result_id"], "prediction_status": status},
            publisher=publish,
        )

    async def reconcile(self, *, task_id=None):
        """Finish terminal bookkeeping without reviving an expired or replaced lease."""
        if self.role == "generation" and task_id is None:
            return
        target = " AND task_id=%s" if task_id else ""
        args = (task_id,) if task_id else ()
        from app.services import task_event_service

        # 收敛后的有界终态处理：逐行锁定取消/过期任务并追加公开事件。
        async with transaction() as conn:
            await job_service.finalize_terminal_rows(conn, task_id=task_id)
        rows = await fetch_all(
            "SELECT task_id FROM quiz_tasks WHERE status IN ('failed','cancelled') "
            "AND stage IN ('failed','cancelled')"
            + target
            + " ORDER BY updated_at LIMIT 100",
            args,
        )
        for item in rows:
            async with transaction() as conn:
                raw = await fetch_one(
                    "SELECT * FROM quiz_tasks WHERE task_id=%s FOR UPDATE",
                    (item["task_id"],),
                    conn=conn,
                )
                if (
                    not raw
                    or raw["status"] not in {"failed", "cancelled"}
                    or raw["stage"] not in {"failed", "cancelled"}
                ):
                    continue
                job = job_service.decode(raw)
                request = job["request"] or {}
                code = job["error_code"] or "cancelled"
                if job["kind"] in {"quiz", "practice_generate"}:
                    from app.services.review_service import reconcile_review_generation

                    await reconcile_review_generation(conn, job)
                if job["kind"] == "ingest" and request.get("build_id"):
                    await execute(
                        "UPDATE kb_index_builds SET status='failed' WHERE build_id=%s AND owner_id=%s AND status='building'",
                        (request["build_id"], job["user_id"]),
                        conn=conn,
                    )
                    await execute(
                        "UPDATE kb_documents SET status=IF(active_build_id IS NULL,'failed','ready'),error_code=%s,"
                        "error_message='资料处理未完成，请查看错误原因后重试' WHERE doc_id=%s AND user_id=%s "
                        "AND document_revision=%s AND deleted_at IS NULL",
                        (
                            code,
                            request["doc_id"],
                            job["user_id"],
                            request["document_revision"],
                        ),
                        conn=conn,
                    )
                elif job["kind"] == "qa" and request.get("session_id"):
                    await execute(
                        "UPDATE qa_sessions SET active_task_id=NULL,updated_at=UTC_TIMESTAMP(6) "
                        "WHERE session_id=%s AND owner_id=%s AND active_task_id=%s",
                        (request["session_id"], job["user_id"], job["task_id"]),
                        conn=conn,
                    )
                    await execute(
                        "UPDATE qa_messages SET status=%s,error_code=%s,finished_at=COALESCE(finished_at,UTC_TIMESTAMP(6)) "
                        "WHERE task_id=%s AND owner_id=%s AND role='assistant'",
                        (job["status"], code, job["task_id"], job["user_id"]),
                        conn=conn,
                    )
                elif job["kind"] == "report" and request.get("quiz_id"):
                    await execute(
                        "UPDATE reports SET status='failed',error_code=%s WHERE quiz_id=%s AND user_id=%s "
                        "AND stats_revision=%s AND status IN ('pending','running')",
                        (
                            code,
                            request["quiz_id"],
                            job["user_id"],
                            request["stats_revision"],
                        ),
                        conn=conn,
                    )
                elif job["kind"] == "learning_project":
                    from app.workers.learning_projection_job import (
                        reconcile_learning_projection,
                    )

                    await reconcile_learning_projection(conn, job)
                elif job["kind"] in {"practice_generate", "practice_grade"}:
                    from app.workers.practice_job import reconcile_practice_job

                    await reconcile_practice_job(job, conn)
                elif job["kind"] in {"course_outline", "course_lesson"}:
                    from app.workers.course_job import reconcile_course

                    await reconcile_course(job, conn)
                elif job["kind"] == "course_tutor":
                    from app.workers.course_tutor_job import reconcile_course_tutor

                    await reconcile_course_tutor(job, conn)
                elif job["kind"] in {"course_application_generate", "course_application_feedback"}:
                    from app.workers.course_application_job import reconcile_course_application

                    await reconcile_course_application(job, conn)
                elif job["kind"] == "images" and request.get("quiz_id"):
                    await execute(
                        "UPDATE quiz_sessions SET images_status='failed' WHERE quiz_id=%s AND user_id=%s "
                        "AND images_status IN ('pending','running')",
                        (request["quiz_id"], job["user_id"]),
                        conn=conn,
                    )
                elif job["kind"] == "eval_sample" and request.get("result_id"):
                    await execute(
                        "UPDATE eval_results SET status=%s,prediction_status=%s,error_code=%s "
                        "WHERE result_id=%s AND status IN ('queued','running')",
                        (job["status"], job["status"], code, request["result_id"]),
                        conn=conn,
                    )
                await execute(
                    "UPDATE quiz_tasks SET stage=%s WHERE task_id=%s",
                    (job["status"] + "_reconciled", job["task_id"]),
                    conn=conn,
                )
                # 调和完成后同事务写一次 settled 事件：business_settled 翻真。
                await task_event_service.append_settled_event(conn, job)

    async def serve(self, stop_event=None, *, poll_seconds=2):
        stop_event = stop_event or asyncio.Event()
        while not stop_event.is_set():
            if not await self.run_once():
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=poll_seconds)
                except asyncio.TimeoutError:
                    pass


async def _main(args):
    from app.core.redis_client import close_redis, init_redis
    from app.workers.providers import build_runtime

    await init_pool()
    # 通知客户端与 API 共享同一套 Redis 运行时；初始化失败只降级。
    await init_redis()
    runtime = None
    worker = None
    try:
        from app.workers.roles import effective_role
        role = effective_role(get_settings(), args.role)
        runtime = build_runtime(role=role)
        worker = OwnerWorker(
            runtime.engine,
            report_generator=runtime.report_generator,
            practice_provider=runtime.practice_provider,
            grading_provider=runtime.grading_provider,
            course_generator=runtime.course_generator,
            course_tutor_generator=runtime.course_tutor_generator,
            course_application_generator=runtime.course_application_generator,
            worker_id=args.worker_id,
            role=role,
        )
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for name in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError, RuntimeError, ValueError):
                loop.add_signal_handler(name, stop.set)
        if args.once or args.task_id:
            await worker.run_once(task_id=args.task_id)
        else:
            await worker.serve(stop, poll_seconds=args.poll_seconds)
    finally:
        if worker is not None:
            await execute("DELETE FROM worker_heartbeats WHERE worker_id=%s", (worker.worker_id,))
        if runtime is not None:
            await runtime.close()
        await close_redis()
        await close_mysql_pool()


def main():
    parser = argparse.ArgumentParser(description="Run the sole durable RAG/index owner")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--task-id")
    parser.add_argument("--worker-id")
    parser.add_argument("--role", choices=["owner", "writer", "generation"])
    parser.add_argument("--poll-seconds", type=float, default=2)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("poll-seconds must be positive")
    logging.basicConfig(level=get_settings().log_level)
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
