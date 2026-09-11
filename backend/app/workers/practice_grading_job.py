"""Lease/input/head fenced grading and body-free terminal reconciliation."""

from app.core.db import execute, fetch_one, transaction
from app.core.errors import conflict, not_found
from app.core.values import dump, load, now
from app.learning.contracts import AssessmentDraft
from app.practice.contracts import GradeArtifact, PracticeUsage
from app.practice.pipeline import await_if_needed
from app.practice.short_answer import GradingPorts, grade_short_answer
from app.rag.contracts import BudgetLimits, ExecutionContext, ResolvedScope, stable_hash
from app.rag.errors import ScopeRevoked
from app.services import job_service, practice_service
from app.services import learning_event_service as events
from app.services import practice_grading_service as grading


def _same_artifact(snapshot, artifact):
    for field in (
        "owner_id",
        "mode",
        "run_id",
        "attempt_id",
        "grading_request_id",
        "question_version",
        "rubric_version",
        "rubric_hash",
        "response_hash",
        "scope_fingerprint",
        "grader_version",
        "model_fingerprint",
        "prompt_version",
        "prompt_hash",
    ):
        if getattr(snapshot, field) != getattr(artifact, field):
            raise ScopeRevoked("Grading output does not match the frozen input")
    if artifact.assessment.source != "model":
        raise ScopeRevoked("Automatic grading cannot select another authority")


async def run_practice_grading(job, actor, engine, *, provider, usage_loader):
    state = await grading.authorize_grading_execution(job)
    snapshot, scope = state.snapshot, state.scope
    if actor.owner_id != snapshot.owner_id:
        raise ScopeRevoked("Grading requires its production owner")
    configuration = grading.grading_model_configuration()
    if (
        provider is None
        or getattr(provider, "model_fingerprint", None) != snapshot.model_fingerprint
        or getattr(provider, "output_token_limit", None)
        != configuration["output_token_limit"]
        or getattr(provider, "model_context_window", None)
        != configuration["model_context_window"]
    ):
        raise conflict("grading_configuration_changed", "评分模型与原始配置不一致")
    async with transaction() as conn:
        await grading.authorize_grading_execution(job, conn=conn)
        await execute(
            "UPDATE practice_grading_requests SET status='running' WHERE grading_request_id=%s AND active_task_id=%s",
            (snapshot.grading_request_id, job["task_id"]),
            conn=conn,
        )
    context = ExecutionContext(
        mode="production",
        run_id=snapshot.run_id,
        storage_namespace=scope.namespace,
        budget=BudgetLimits(
            max_llm_calls=2,
            max_embedding_calls=0,
            max_reranker_calls=0,
            max_search_calls=0,
            max_fetch_calls=0,
            max_input_tokens=configuration["model_context_window"] * 2,
            max_output_tokens=configuration["output_token_limit"] * 2,
            deadline_seconds=min(
                1800, max(0.001, (job["deadline_at"] - now()).total_seconds())
            ),
        ),
    )

    async def reauthorize(value):
        current = await grading.authorize_grading_execution(job)
        if value != scope or current.scope != scope or current.snapshot != snapshot:
            raise ScopeRevoked("Frozen grading scope changed")
        return current.scope

    await job_service.heartbeat(job, "grading")
    artifact = await grade_short_answer(
        snapshot,
        actor,
        context,
        scope,
        GradingPorts(
            grade=provider.grade,
            reauthorize=reauthorize,
            verify_evidence=engine.verify_evidence,
            measure_input_tokens=provider.measure_input_tokens,
        ),
        profile=grading.current_snapshot_profile(snapshot),
    )
    _same_artifact(snapshot, artifact)
    usage = PracticeUsage.model_validate(
        await usage_loader(actor.owner_id, "production", snapshot.grading_request_id)
    )
    artifact = GradeArtifact.model_validate(
        {
            **artifact.model_dump(mode="json"),
            "usage": usage.model_dump(mode="json"),
        }
    )
    await job_service.heartbeat(job, "publishing")

    async def publish(current, result, conn):
        locked = await grading.authorize_grading_execution(job, conn=conn)
        if locked.snapshot != snapshot or locked.scope != scope:
            raise ScopeRevoked("Grading input changed before publication")
        for evidence in snapshot.evidence:
            if await await_if_needed(engine.verify_evidence(evidence, scope)) is False:
                raise ScopeRevoked("Grading evidence changed before publication")
        payload = artifact.model_dump(mode="json")
        if (
            payload["assessment"]["confirmation"] == "confirmed"
            and grading.current_snapshot_profile(snapshot) is None
        ):
            payload["assessment"]["confirmation"] = "provisional"
            payload["assessment"]["independent_eligible"] = False
            payload["calibration_profile_hash"] = None
        payload["assessment"]["supersedes_assessment_id"] = (
            locked.head["assessment_id"] if locked.head else None
        )
        sealed = GradeArtifact.model_validate(payload)
        _same_artifact(snapshot, sealed)
        ref = await events.record_assessment(
            conn, actor.owner_id, snapshot.attempt_id, sealed.assessment
        )
        changed = await execute(
            "UPDATE practice_grading_requests SET status='completed',revision=revision+1,"
            "latest_assessment_id=%s,artifact_json=%s,error_code=NULL "
            "WHERE grading_request_id=%s AND active_task_id=%s AND revision=%s",
            (
                ref.assessment_id,
                dump(sealed),
                snapshot.grading_request_id,
                current["task_id"],
                locked.grading["revision"],
            ),
            conn=conn,
        )
        if changed != 1:
            raise conflict("grading_revision_conflict", "评分任务已更新")
        saved = await fetch_one(
            "SELECT artifact_json FROM practice_grading_requests WHERE grading_request_id=%s FOR UPDATE",
            (snapshot.grading_request_id,),
            conn=conn,
        )
        persisted = GradeArtifact.model_validate(load(saved["artifact_json"]))
        _same_artifact(snapshot, persisted)
        if persisted.assessment != sealed.assessment:
            raise not_found()
        result.update(
            attempt_id=snapshot.attempt_id,
            assessment_id=ref.assessment_id,
            status="completed",
        )

    await job_service.complete_job(job, {}, publisher=publish)


async def reconcile_practice_grading(job, conn):
    """Keep fees and append a minimal provisional fact only for the active task.

    This path reads no answer, evidence excerpt, rubric body or frozen JSON. It
    still works after source cleanup has erased task/request bodies.
    """
    if conn is None:
        raise ValueError("Grading reconciliation requires the existing transaction")
    if (job.get("kind"), job.get("mode"), job.get("status")) not in {
        ("practice_grade", "production", "failed"),
        ("practice_grade", "production", "cancelled"),
    }:
        return
    current = await practice_service.owned_practice_task(
        job["user_id"], job["task_id"], conn=conn, lock=True
    )
    if current["status"] not in {"failed", "cancelled"}:
        return
    preview = await fetch_one(
        "SELECT s.practice_id,p.space_id FROM practice_grading_requests g "
        "JOIN practice_submissions s ON s.attempt_id=g.attempt_id AND s.owner_id=g.owner_id "
        "JOIN practice_sessions p ON p.practice_id=s.practice_id AND p.owner_id=s.owner_id "
        "WHERE g.active_task_id=%s AND g.owner_id=%s",
        (current["task_id"], current["user_id"]),
        conn=conn,
    )
    if preview is None:
        return
    await practice_service.lock_practice_space(
        conn, current["user_id"], preview["space_id"]
    )
    practice = await fetch_one(
        "SELECT practice_id,owner_id,space_id,scope_revision,source_scope_json,error_code "
        "FROM practice_sessions WHERE practice_id=%s AND owner_id=%s FOR UPDATE",
        (preview["practice_id"], current["user_id"]),
        conn=conn,
    )
    row = await fetch_one(
        "SELECT grading_request_id,owner_id,attempt_id,request_hash,active_task_id,status,revision,latest_assessment_id,error_code "
        "FROM practice_grading_requests WHERE active_task_id=%s AND owner_id=%s FOR UPDATE",
        (current["task_id"], current["user_id"]),
        conn=conn,
    )
    if row is None or row["status"] not in {"pending", "running"}:
        return
    await events._locked_attempt(
        conn, current["user_id"], row["attempt_id"], minimal_terminal=True
    )
    question = await fetch_one(
        "SELECT a.question_id,a.question_version,a.response_hash,a.space_id,a.scope_revision,"
        "q.rubric_version,q.rubric_hash FROM learning_attempts a "
        "JOIN practice_submissions s ON s.attempt_id=a.attempt_id AND s.owner_id=a.owner_id "
        "JOIN practice_questions q ON q.practice_id=s.practice_id AND q.question_id=s.question_id AND q.owner_id=s.owner_id "
        "WHERE a.attempt_id=%s AND a.owner_id=%s AND a.origin_kind='practice' AND a.origin_id=%s "
        "AND a.answer_kind='short_answer' AND a.question_version=q.question_version FOR SHARE",
        (row["attempt_id"], current["user_id"], practice["practice_id"]),
        conn=conn,
    )
    if question is None or (question["space_id"], question["scope_revision"]) != (
        practice["space_id"],
        practice["scope_revision"],
    ):
        raise not_found()
    scope = ResolvedScope.model_validate(load(practice["source_scope_json"]))
    if ResolvedScope.model_validate(current["scope"]) != scope:
        raise not_found()
    request = None
    if current["request"]:
        request = grading.task_request(current["request"])
        expected = {
            "grading_request_id": row["grading_request_id"],
            "attempt_id": row["attempt_id"],
            "practice_id": practice["practice_id"],
            "space_id": question["space_id"],
            "scope_revision": question["scope_revision"],
            "scope_fingerprint": scope.fingerprint,
            "question_version": question["question_version"],
            "rubric_version": question["rubric_version"],
            "rubric_hash": question["rubric_hash"],
            "response_hash": question["response_hash"],
            "grading_request_hash": row["request_hash"],
            "grading_revision": row["revision"],
            "expected_assessment_id": row["latest_assessment_id"],
        }
        if request.model_dump(mode="json") != expected or current[
            "request_hash"
        ] != stable_hash(expected):
            return
    elif (
        practice["error_code"] != "source_revoked"
        or row["error_code"] != "source_revoked"
    ):
        raise not_found()
    # The shared terminal path authorizes persistent identities and allows only
    # the documented body-free exception when sources have been revoked.
    head = await fetch_one(
        "SELECT a.assessment_id,a.source,a.confirmation FROM learning_assessment_heads h "
        "JOIN assessment_records a ON a.assessment_id=h.assessment_id AND a.attempt_id=h.attempt_id AND a.owner_id=h.owner_id "
        "WHERE h.attempt_id=%s AND h.owner_id=%s FOR UPDATE",
        (row["attempt_id"], current["user_id"]),
        conn=conn,
    )
    if (
        head and (head["source"] == "human" or head["confirmation"] == "confirmed")
    ) or (row["latest_assessment_id"] != (head["assessment_id"] if head else None)):
        return
    ref = await events.record_assessment(
        conn,
        current["user_id"],
        row["attempt_id"],
        AssessmentDraft(
            status=current["status"],
            source="model",
            confirmation="provisional",
            grader_version="practice-grading-terminal-v1",
            rubric_version=question["rubric_version"],
            rubric_hash=question["rubric_hash"],
            supersedes_assessment_id=head["assessment_id"] if head else None,
        ),
    )
    await execute(
        "UPDATE practice_grading_requests SET status=%s,revision=revision+1,latest_assessment_id=%s,error_code=%s "
        "WHERE grading_request_id=%s AND active_task_id=%s AND revision=%s",
        (
            current["status"],
            ref.assessment_id,
            current["error_code"] or "cancelled",
            row["grading_request_id"],
            current["task_id"],
            row["revision"],
        ),
        conn=conn,
    )
