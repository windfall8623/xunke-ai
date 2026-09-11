"""Durable short-answer requests and append-only owned adjudication.

Existing task locks precede space, practice, grading request, source and head
locks. A retry keeps the exact original grading snapshot and logical quota.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import Field, ValidationError
from pymysql import IntegrityError, OperationalError

from app.core.db import execute, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import dump, load, uid
from app.learning.contracts import AssessmentRef, LearningId
from app.models.practice_grading import (
    PracticeReviewBody,
    PracticeSelfReviewBody,
    PracticeSelfReviewReceipt,
)
from app.practice.calibration import calibration_profile_applies
from app.practice.contracts import ShortAnswer
from app.practice.grade_contracts import GradeInputSnapshot, ShortAnswerProposal
from app.practice.grading_config import (
    grading_model_configuration,
    load_grading_profile,
    require_generation_types as require_generation_types,
    require_short_answer_grading as require_short_answer_grading,
)
from app.practice.short_answer import (
    grading_identity,
    proposal_assessment,
    proposal_errors,
)
from app.prompts.practice_grade_prompt import (
    GRADER_VERSION,
    PROMPT_HASH,
    PROMPT_VERSION,
)
from app.rag.contracts import Contract, Hash, ResolvedScope, stable_hash
from app.services import job_service, practice_service
from app.services import learning_event_service as events


class GradingTaskRequest(Contract):
    grading_request_id: LearningId
    attempt_id: LearningId
    practice_id: LearningId
    space_id: LearningId
    scope_revision: int = Field(ge=1)
    question_version: Hash
    rubric_version: LearningId
    rubric_hash: Hash
    response_hash: Hash
    scope_fingerprint: Hash
    grading_request_hash: Hash
    grading_revision: int = Field(ge=0)
    expected_assessment_id: LearningId | None


@dataclass(frozen=True)
class GradingState:
    practice: dict
    generation: practice_service.PracticeGenerationRequest
    scope: ResolvedScope
    grading: dict
    snapshot: GradeInputSnapshot
    attempt: dict
    head: dict | None


def _changed():
    return conflict("grading_revision_conflict", "评分版本已更新，请读取当前结果后重试")


def task_request(raw):
    try:
        return GradingTaskRequest.model_validate(raw)
    except (ValueError, TypeError) as exc:
        raise not_found() from exc


def grading_snapshot(row):
    try:
        raw = load(row["request_json"])
        snapshot = GradeInputSnapshot.model_validate(raw)
        if (
            stable_hash(raw) != row["request_hash"]
            or stable_hash(snapshot.model_dump(mode="json")) != row["request_hash"]
            or (snapshot.owner_id, snapshot.attempt_id, snapshot.grading_request_id)
            != (row["owner_id"], row["attempt_id"], row["grading_request_id"])
            or snapshot.mode != "production"
        ):
            raise not_found()
        return snapshot
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise not_found() from exc


def _task_payload(practice_id, snapshot, request_hash, revision, head_id):
    return GradingTaskRequest(
        **{
            key: getattr(snapshot, key)
            for key in (
                "grading_request_id",
                "attempt_id",
                "space_id",
                "scope_revision",
                "question_version",
                "rubric_version",
                "rubric_hash",
                "response_hash",
                "scope_fingerprint",
            )
        },
        practice_id=practice_id,
        grading_request_hash=request_hash,
        grading_revision=revision,
        expected_assessment_id=head_id,
    ).model_dump(mode="json")


def require_grading_job(job, state, *, current=False):
    request = task_request(job.get("request"))
    expected = _task_payload(
        state.practice["practice_id"],
        state.snapshot,
        state.grading["request_hash"],
        request.grading_revision,
        request.expected_assessment_id,
    )
    try:
        scope = ResolvedScope.model_validate(job["scope"])
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise not_found() from exc
    if (
        job["user_id"] != state.snapshot.owner_id
        or (job["kind"], job["operation"], job["mode"])
        != ("practice_grade", "practice.grade", "production")
        or request.model_dump(mode="json") != expected
        or job["request_hash"] != stable_hash(expected)
        or scope != state.scope
    ):
        raise not_found()
    if current and (
        state.grading["active_task_id"] != job["task_id"]
        or state.grading["revision"] != request.grading_revision
        or state.grading["status"] not in {"pending", "running"}
        or (state.head["assessment_id"] if state.head else None)
        != request.expected_assessment_id
        or state.head
        and (
            state.head["source"] == "human" or state.head["confirmation"] == "confirmed"
        )
    ):
        raise _changed()
    return request


def require_current_grader(snapshot):
    if snapshot.model_fingerprint != stable_hash(grading_model_configuration()) or (
        snapshot.prompt_hash,
        snapshot.prompt_version,
        snapshot.grader_version,
    ) != (PROMPT_HASH, PROMPT_VERSION, GRADER_VERSION):
        raise conflict(
            "grading_configuration_changed", "评分配置已变化，不能用重试改变原评分依据"
        )


def current_snapshot_profile(snapshot):
    profile = load_grading_profile()
    if (
        snapshot.calibration_profile_hash is None
        or not calibration_profile_applies(profile, grading_identity(snapshot))
        or profile["profile_hash"] != snapshot.calibration_profile_hash
    ):
        return None
    return profile


async def _attempt_preview(conn, owner_id, attempt_id):
    preview = await fetch_one(
        "SELECT s.practice_id,p.space_id,p.generation_task_id,p.generation_request_json,"
        "g.grading_request_id,g.active_task_id FROM practice_submissions s "
        "JOIN practice_sessions p ON p.practice_id=s.practice_id AND p.owner_id=s.owner_id "
        "LEFT JOIN practice_grading_requests g ON g.attempt_id=s.attempt_id AND g.owner_id=s.owner_id "
        "WHERE s.attempt_id=%s AND s.owner_id=%s",
        (attempt_id, owner_id),
        conn=conn,
    )
    if preview is None or preview["grading_request_id"] is None:
        raise not_found()
    return preview


async def locked_grading_state(conn, owner_id, attempt_id, *, job=None):
    """The optional job is already locked; otherwise prelock the active task."""
    preview = await _attempt_preview(conn, owner_id, attempt_id)
    if job is None and preview["active_task_id"]:
        await practice_service.owned_practice_task(
            owner_id, preview["active_task_id"], conn=conn, lock=True
        )
    hint = practice_service.generation_request(preview["generation_request_json"])
    if hint.origin is not None:
        await practice_service.owned_practice_task(
            owner_id, preview["generation_task_id"], conn=conn, lock=True
        )
    await practice_service.lock_practice_space(conn, owner_id, preview["space_id"])
    practice = await practice_service.owned_practice(
        owner_id, preview["practice_id"], conn=conn, lock=True
    )
    grading = await fetch_one(
        "SELECT * FROM practice_grading_requests WHERE attempt_id=%s AND owner_id=%s FOR UPDATE",
        (attempt_id, owner_id),
        conn=conn,
    )
    if (
        grading is None
        or grading["grading_request_id"] != preview["grading_request_id"]
    ):
        raise not_found()
    if job is None and grading["active_task_id"] != preview["active_task_id"]:
        raise conflict("grading_task_changed", "评分任务已更新，请重试")
    practice, generation, scope = await practice_service.authorize_practice(
        conn, owner_id, practice["practice_id"]
    )
    artifact = await practice_service.checked_practice_artifact(
        conn, practice, generation, scope
    )
    snapshot = grading_snapshot(grading)
    _, attempt, question = await events._locked_attempt(conn, owner_id, attempt_id)
    if (
        attempt["origin_kind"] != "practice"
        or attempt["origin_id"] != practice["practice_id"]
        or attempt["answer_kind"] != "short_answer"
        or (snapshot.space_id, snapshot.scope_revision, snapshot.scope_fingerprint)
        != (practice["space_id"], practice["scope_revision"], scope.fingerprint)
        or snapshot.question.model_dump(mode="json") != question
        or snapshot.question.id != attempt["question_id"]
        or snapshot.question_version != attempt["question_version"]
        or snapshot.question_version
        != artifact.question_versions[attempt["question_id"]]
        or snapshot.rubric_hash != artifact.rubric_hashes[attempt["question_id"]]
        or snapshot.rubric_version != snapshot.question.rubric.version
        or snapshot.response_hash != attempt["response_hash"]
        or snapshot.response_hash
        != stable_hash(snapshot.answer.model_dump(mode="json"))
        or snapshot.answer.model_dump(mode="json") != load(attempt["answer_json"])
        or snapshot.help_usage != attempt["help_usage"]
        or snapshot.evidence != artifact.evidence_pack.evidence
    ):
        raise not_found()
    head = await fetch_one(
        "SELECT a.assessment_id,a.source,a.confirmation,a.status,a.revision "
        "FROM learning_assessment_heads h JOIN assessment_records a "
        "ON a.assessment_id=h.assessment_id AND a.attempt_id=h.attempt_id "
        "AND a.owner_id=h.owner_id AND a.revision=h.revision "
        "WHERE h.attempt_id=%s AND h.owner_id=%s FOR UPDATE",
        (attempt_id, owner_id),
        conn=conn,
    )
    if grading["latest_assessment_id"] != (head["assessment_id"] if head else None):
        raise _changed()
    return GradingState(practice, generation, scope, grading, snapshot, attempt, head)


async def checked_grading_task(conn, owner_id, job):
    """Validate a historical task before P03 projects the current public attempt."""
    request = task_request(job.get("request"))
    state = await locked_grading_state(conn, owner_id, request.attempt_id, job=job)
    require_grading_job(job, state)
    return state.snapshot


async def authorize_grading_execution(job, *, conn=None):
    """The exact same pre-call fence is used by the worker and money meter."""
    if conn is None:
        async with transaction() as tx:
            return await authorize_grading_execution(job, conn=tx)
    current = await job_service.locked_job(job, conn)
    if any(
        current.get(field) != job.get(field)
        for field in (
            "task_id",
            "user_id",
            "kind",
            "operation",
            "mode",
            "request_hash",
            "request",
            "scope",
        )
    ):
        raise not_found()
    require_short_answer_grading()
    request = task_request(current["request"])
    state = await locked_grading_state(
        conn, current["user_id"], request.attempt_id, job=current
    )
    require_grading_job(current, state, current=True)
    require_current_grader(state.snapshot)
    return state


async def queue_short_answer(
    conn, actor, *, practice, request, artifact, question, attempt_id
):
    """Called only after the immutable attempt/submission insert in the same tx."""
    if conn is None or not conn.get_transaction_status():
        raise ValueError("Grading requests require the answer transaction")
    require_short_answer_grading()
    if question.type != "short_answer":
        raise not_found()
    attempt = await fetch_one(
        "SELECT * FROM learning_attempts WHERE attempt_id=%s AND owner_id=%s FOR UPDATE",
        (attempt_id, actor.owner_id),
        conn=conn,
    )
    if attempt is None or (
        attempt["origin_kind"],
        attempt["origin_id"],
        attempt["question_id"],
        attempt["space_id"],
        attempt["scope_revision"],
        attempt["question_version"],
    ) != (
        "practice",
        practice["practice_id"],
        question.id,
        request.spec.space_id,
        request.spec.scope_revision,
        artifact.question_versions[question.id],
    ):
        raise not_found()
    existing = await fetch_one(
        "SELECT grading_request_id,active_task_id FROM practice_grading_requests "
        "WHERE attempt_id=%s AND owner_id=%s FOR UPDATE",
        (attempt_id, actor.owner_id),
        conn=conn,
    )
    if existing:
        if not existing["active_task_id"]:
            raise _changed()
        return existing["grading_request_id"], existing["active_task_id"]
    grading_id = uid("grade")
    snapshot = GradeInputSnapshot(
        owner_id=actor.owner_id,
        mode="production",
        run_id=uid("grade_run"),
        attempt_id=attempt_id,
        grading_request_id=grading_id,
        space_id=practice["space_id"],
        scope_revision=practice["scope_revision"],
        scope_fingerprint=request.scope_fingerprint,
        question=question,
        answer=ShortAnswer.model_validate(load(attempt["answer_json"])),
        question_version=attempt["question_version"],
        rubric_version=question.rubric.version,
        rubric_hash=artifact.rubric_hashes[question.id],
        response_hash=attempt["response_hash"],
        evidence=artifact.evidence_pack.evidence,
        help_usage=attempt["help_usage"],
        model_fingerprint=stable_hash(grading_model_configuration()),
        prompt_hash=PROMPT_HASH,
        prompt_version=PROMPT_VERSION,
        grader_version=GRADER_VERSION,
    )
    profile = load_grading_profile()
    if calibration_profile_applies(profile, grading_identity(snapshot)):
        snapshot = snapshot.model_copy(
            update={"calibration_profile_hash": profile["profile_hash"]}
        )
    await execute(
        "INSERT INTO practice_grading_requests(grading_request_id,owner_id,attempt_id,"
        "request_hash,request_json,status,revision) VALUES(%s,%s,%s,%s,%s,'pending',0)",
        (grading_id, actor.owner_id, attempt_id, "0" * 64, dump(snapshot)),
        conn=conn,
    )
    # JSON scores/telemetry can change their final floating digit in MySQL.
    # Seal the actual stored representation before any job can reference it.
    stored = await fetch_one(
        "SELECT request_json FROM practice_grading_requests WHERE grading_request_id=%s FOR UPDATE",
        (grading_id,),
        conn=conn,
    )
    persisted = GradeInputSnapshot.model_validate(load(stored["request_json"]))
    if persisted.model_copy(update={"evidence": snapshot.evidence}) != snapshot:
        raise not_found()
    request_hash = stable_hash(persisted.model_dump(mode="json"))
    await execute(
        "UPDATE practice_grading_requests SET request_hash=%s WHERE grading_request_id=%s",
        (request_hash, grading_id),
        conn=conn,
    )
    payload = _task_payload(practice["practice_id"], persisted, request_hash, 0, None)
    task = await job_service.enqueue_job(
        actor.owner_id,
        "practice_grade",
        payload,
        f"grade:{grading_id}:initial",
        scope=artifact.evidence_pack.resolved_scope.model_dump(mode="json"),
        request_hash=stable_hash(payload),
        conn=conn,
    )
    await execute(
        "UPDATE practice_grading_requests SET active_task_id=%s WHERE grading_request_id=%s",
        (task["task_id"], grading_id),
        conn=conn,
    )
    return grading_id, task["task_id"]


async def _retry_once(actor, attempt_id, key):
    async with transaction() as conn:
        state = await locked_grading_state(conn, actor.owner_id, attempt_id)
        task_key = "grade-retry:" + stable_hash({"attempt_id": attempt_id, "key": key})
        replay = await fetch_one(
            "SELECT * FROM quiz_tasks WHERE user_id=%s AND operation='practice.grade' AND idempotency_key=%s",
            (actor.owner_id, task_key),
            conn=conn,
        )
        if replay:
            replay = job_service.decode(replay)
            require_grading_job(replay, state)
            return replay["task_id"]
        if state.grading["status"] in {"pending", "running"}:
            if not state.grading["active_task_id"]:
                raise _changed()
            return state.grading["active_task_id"]
        require_short_answer_grading()
        require_current_grader(state.snapshot)
        if (
            state.grading["status"] not in {"failed", "cancelled"}
            or state.head
            and (
                state.head["source"] == "human"
                or state.head["confirmation"] == "confirmed"
            )
        ):
            raise conflict("grading_not_retryable", "当前评分不能自动重试")
        logical_key = (
            f"production:practice_grade:{state.snapshot.grading_request_id}:llm"
        )
        account = await fetch_one(
            "SELECT used,reserved FROM budget_accounts WHERE account_key=%s AND resource_type='calls' FOR UPDATE",
            (logical_key,),
            conn=conn,
        )
        if account and account["used"] + account["reserved"] >= 2:
            raise AppError(429, "budget_exceeded", "本次作答的自动评分调用额度已用完")
        revision = state.grading["revision"] + 1
        payload = _task_payload(
            state.practice["practice_id"],
            state.snapshot,
            state.grading["request_hash"],
            revision,
            state.head["assessment_id"] if state.head else None,
        )
        # The user key selects a retry receipt; the immutable snapshot stays put.
        task = await job_service.enqueue_job(
            actor.owner_id,
            "practice_grade",
            payload,
            task_key,
            scope=state.scope.model_dump(mode="json"),
            request_hash=stable_hash(payload),
            conn=conn,
        )
        await execute(
            "UPDATE practice_grading_requests SET active_task_id=%s,status='pending',revision=%s,error_code=NULL "
            "WHERE grading_request_id=%s AND revision=%s",
            (
                task["task_id"],
                revision,
                state.snapshot.grading_request_id,
                state.grading["revision"],
            ),
            conn=conn,
        )
        return task["task_id"]


async def _bounded_transaction(operation):
    for attempt in range(3):
        try:
            return await operation()
        except OperationalError as exc:
            if exc.args[0] not in {1205, 1213} or attempt == 2:
                raise
        except IntegrityError:
            if attempt == 2:
                raise
        except AppError as exc:
            if exc.code != "grading_task_changed" or attempt == 2:
                raise


async def retry_practice_grading(actor, attempt_id, key):
    practice_service._validate_key(key)
    task_id = await _bounded_transaction(lambda: _retry_once(actor, attempt_id, key))
    return await practice_service.get_practice_task(actor.owner_id, task_id)


async def _review_once(actor, attempt_id, body, key, request_hash):
    async with transaction() as conn:
        # Foreign attempts stay hidden even from an evaluator.
        await _attempt_preview(conn, actor.owner_id, attempt_id)
        if "evaluator" not in actor.roles:
            raise AppError(403, "evaluator_required", "权威复核需要评测维护权限")
        state = await locked_grading_state(conn, actor.owner_id, attempt_id)
        replay = await fetch_one(
            "SELECT * FROM practice_review_receipts WHERE owner_id=%s AND idempotency_key=%s FOR UPDATE",
            (actor.owner_id, key),
            conn=conn,
        )
        if replay:
            if (
                replay["request_hash"] != request_hash
                or replay["attempt_id"] != attempt_id
            ):
                raise conflict("idempotency_conflict", "相同操作标识已用于不同复核")
            ref = AssessmentRef.model_validate(load(replay["receipt_json"]))
            if (ref.attempt_id, ref.assessment_id) != (
                attempt_id,
                replay["assessment_id"],
            ):
                raise not_found()
            return ref
        if body.expected_grading_revision != state.grading[
            "revision"
        ] or body.expected_assessment_id != (
            state.head["assessment_id"] if state.head else None
        ):
            raise _changed()
        proposal = ShortAnswerProposal(
            status="graded",
            criterion_results=[
                item.model_dump(mode="json") for item in body.criterion_results
            ],
            feedback=body.feedback,
        )
        refs = {
            ref for item in proposal.criterion_results for ref in item.evidence_refs
        }
        if (
            proposal_errors(proposal, state.snapshot)
            or len(body.evidence_refs) != len(set(body.evidence_refs))
            or set(body.evidence_refs) != refs
        ):
            raise AppError(
                422, "invalid_review", "复核必须覆盖固定评分要点及其原始证据"
            )
        draft = proposal_assessment(
            proposal, state.snapshot, confirmed=True, source="human"
        )
        draft = draft.model_copy(
            update={
                "supersedes_assessment_id": body.expected_assessment_id,
                "grader_version": "human-short-answer-review-v1",
            }
        )
        if state.grading["active_task_id"]:
            await job_service.cancel_job(
                actor.owner_id, state.grading["active_task_id"], conn=conn
            )
        ref = await events.record_assessment(conn, actor.owner_id, attempt_id, draft)
        await execute(
            "UPDATE practice_grading_requests SET active_task_id=NULL,status='completed',"
            "revision=revision+1,latest_assessment_id=%s,error_code=NULL WHERE grading_request_id=%s AND revision=%s",
            (
                ref.assessment_id,
                state.snapshot.grading_request_id,
                state.grading["revision"],
            ),
            conn=conn,
        )
        await execute(
            "INSERT INTO practice_review_receipts(owner_id,idempotency_key,attempt_id,"
            "assessment_id,request_hash,receipt_json) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                actor.owner_id,
                key,
                attempt_id,
                ref.assessment_id,
                request_hash,
                dump(ref),
            ),
            conn=conn,
        )
        return ref


async def review_practice_attempt(actor, attempt_id, body: PracticeReviewBody, key):
    practice_service._validate_key(key)
    body = PracticeReviewBody.model_validate(body.model_dump(mode="json"))
    request_hash = stable_hash(
        {"attempt_id": attempt_id, "body": body.model_dump(mode="json")}
    )
    return await _bounded_transaction(
        lambda: _review_once(actor, attempt_id, body, key, request_hash)
    )


async def self_review_practice_attempt(
    actor, attempt_id, body: PracticeSelfReviewBody, key
):
    from app.services.practice_answer_service import practice_attempt_view

    practice_service._validate_key(key)
    body = PracticeSelfReviewBody.model_validate(body.model_dump(mode="json"))
    async with transaction() as conn:
        await practice_attempt_view(conn, actor.owner_id, attempt_id)
        annotation_id = await events.record_annotation(
            conn,
            actor.owner_id,
            attempt_id,
            kind="self_review",
            payload={**body.model_dump(mode="json"), "independent_eligible": False},
            key=key,
        )
        return PracticeSelfReviewReceipt(annotation_id=annotation_id)
