"""Immutable practice answers and completion facts in the activity transaction.

No rule submission calls a provider or grants XP. Existing job mutations must
enter with their job lock first; newly created outbox jobs share this transaction.
"""

from __future__ import annotations

from datetime import timezone

from pydantic import TypeAdapter, ValidationError
from pymysql import IntegrityError, OperationalError

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import dump, load, now
from app.learning.contracts import AssessmentDraft, LearningAttemptDraft
from app.learning.review_rules import RULE_VERSION
from app.models.practice import (
    PracticeAnswerBody,
    PracticeAttemptView,
    PracticeCompletionReceipt,
    PracticeHelpView,
    PracticeSelfReviewView,
    PracticeSubmissionReceipt,
    public_assessment,
)
from app.practice.contracts import TypedAnswer
from app.practice.grading import grade_rules
from app.rag.contracts import ActorContext, stable_hash
from app.services import learning_event_service as events
from app.services import learning_projection_service as projections
from app.services import practice_service


_ANSWER = TypeAdapter(TypedAnswer)


def _utc(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def canonical_answer(answer: TypedAnswer) -> dict:
    """Identity ordering only: normalization never changes the stored response."""
    typed = _ANSWER.validate_python(answer.model_dump(mode="json"))
    result = typed.model_dump(mode="json")
    if typed.type == "cloze":
        result["blanks"] = sorted(result["blanks"], key=lambda item: item["blank_id"])
    return result


def _question(artifact, question_id):
    question = next((q for q in artifact.questions if q.id == question_id), None)
    if question is None:
        raise not_found()
    return question


def _help_usage(practice, question_id):
    markers = load(practice["help_usage_json"], {})
    value = (
        markers.get(question_id, "unknown") if isinstance(markers, dict) else "unknown"
    )
    return (
        value
        if isinstance(value, str) and value in {"none", "hints", "unknown"}
        else "unknown"
    )


def _submission_receipt(submission, practice, artifact):
    try:
        receipt = PracticeSubmissionReceipt.model_validate(
            load(submission["receipt_json"])
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise not_found() from exc
    if (
        receipt.practice_id != practice["practice_id"]
        or receipt.practice_id != submission["practice_id"]
        or receipt.question_id != submission["question_id"]
        or receipt.attempt_id != submission["attempt_id"]
        or submission["owner_id"] != practice["owner_id"]
        or submission["question_version"]
        != artifact.question_versions.get(receipt.question_id)
        or receipt.accepted_revision > practice["revision"]
    ):
        raise not_found()
    return receipt


async def _submit_once(actor, practice_id, question_id, body, key, request_hash):
    async with transaction() as conn:
        # A read-only locator comes before activity locks. Replays authorize the
        # original activity too, including every uncited source in its scope.
        preview = await fetch_one(
            "SELECT practice_id FROM practice_submissions WHERE owner_id=%s AND idempotency_key=%s",
            (actor.owner_id, key),
            conn=conn,
        )
        practice, request, scope = await practice_service.authorize_practice(
            conn, actor.owner_id, preview["practice_id"] if preview else practice_id
        )
        artifact = await practice_service.checked_practice_artifact(
            conn, practice, request, scope
        )
        existing = await fetch_one(
            "SELECT * FROM practice_submissions WHERE owner_id=%s AND idempotency_key=%s FOR UPDATE",
            (actor.owner_id, key),
            conn=conn,
        )
        if existing:
            if (
                existing["request_hash"] != request_hash
                or existing["practice_id"] != practice_id
                or existing["question_id"] != question_id
            ):
                raise conflict("idempotency_conflict", "相同操作标识已用于不同请求")
            return _submission_receipt(existing, practice, artifact)
        question = _question(artifact, question_id)
        previous = await fetch_one(
            "SELECT attempt_id FROM practice_submissions WHERE owner_id=%s "
            "AND practice_id=%s AND question_id=%s FOR UPDATE",
            (actor.owner_id, practice_id, question_id),
            conn=conn,
        )
        if previous:
            raise conflict("answer_already_submitted", "此题已提交，不能修改原始作答")
        if practice["status"] != "ready":
            raise conflict("activity_completed", "本次练习当前不能提交新作答")
        if body.answer.type != question.type:
            raise AppError(422, "answer_type_mismatch", "作答题型与题目不一致")
        if question.type == "short_answer":
            from app.services.practice_grading_service import (
                require_short_answer_grading,
            )

            require_short_answer_grading()
        try:
            assessment = (
                grade_rules(question, body.answer)
                if question.type != "short_answer"
                else None
            )
            answer_json = canonical_answer(body.answer)
        except (ValueError, TypeError) as exc:
            code = str(exc)
            if code not in {
                "answer_type_mismatch",
                "blank_ids_mismatch",
                "unsupported_numeric_unit",
            }:
                code = "invalid_practice_answer"
            raise AppError(422, code, "作答内容与题目要求不符") from exc
        help_usage = _help_usage(practice, question_id)
        attempt = await events.record_attempt(
            conn,
            actor.owner_id,
            LearningAttemptDraft(
                origin_kind="practice",
                origin_id=practice_id,
                question_id=question_id,
                question_version=artifact.question_versions[question_id],
                space_id=practice["space_id"],
                scope_revision=practice["scope_revision"],
                answer_kind=question.type,
                answer_json=answer_json,
                response_hash=stable_hash(answer_json),
                duration_ms=body.duration_ms,
                help_usage=help_usage,
                occurred_at=_utc(now()),
            ),
        )
        assessment_ref = None
        if assessment is not None:
            assessment_ref = await events.record_assessment(
                conn,
                actor.owner_id,
                attempt.attempt_id,
                assessment.model_copy(
                    update={"independent_eligible": help_usage == "none"}
                ),
            )
        receipt = PracticeSubmissionReceipt(
            practice_id=practice_id,
            question_id=question_id,
            attempt_id=attempt.attempt_id,
            accepted_revision=practice["revision"] + 1,
            assessment_id=assessment_ref.assessment_id if assessment_ref else None,
        )
        await execute(
            "INSERT INTO practice_submissions(attempt_id,owner_id,practice_id,question_id,"
            "question_version,idempotency_key,request_hash,receipt_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                attempt.attempt_id,
                actor.owner_id,
                practice_id,
                question_id,
                artifact.question_versions[question_id],
                key,
                request_hash,
                dump(receipt),
            ),
            conn=conn,
        )
        if question.type == "short_answer":
            from app.services.practice_grading_service import queue_short_answer

            grading_id, task_id = await queue_short_answer(
                conn,
                actor,
                practice=practice,
                request=request,
                artifact=artifact,
                question=question,
                attempt_id=attempt.attempt_id,
            )
            receipt = receipt.model_copy(
                update={"grading_request_id": grading_id, "task_id": task_id}
            )
            await execute(
                "UPDATE practice_submissions SET receipt_json=%s WHERE attempt_id=%s AND owner_id=%s",
                (dump(receipt), attempt.attempt_id, actor.owner_id),
                conn=conn,
            )
        await execute(
            "UPDATE practice_sessions SET revision=revision+1 WHERE practice_id=%s AND owner_id=%s",
            (practice_id, actor.owner_id),
            conn=conn,
        )
        return receipt


async def submit_practice_answer(
    actor: ActorContext,
    practice_id: str,
    question_id: str,
    body: PracticeAnswerBody,
    key: str,
) -> PracticeSubmissionReceipt:
    practice_service._validate_key(key)
    body = PracticeAnswerBody.model_validate(body.model_dump(mode="json"))
    request_hash = stable_hash(
        {
            "practice_id": practice_id,
            "question_id": question_id,
            "body": body.model_dump(mode="json"),
        }
    )
    for attempt in range(3):
        try:
            return await _submit_once(
                actor, practice_id, question_id, body, key, request_hash
            )
        except (IntegrityError, OperationalError) as exc:
            # Different activities can contend for the owner's unique key.
            # Retrying after rollback locates the winner before acquiring roots.
            if not exc.args or exc.args[0] not in {1062, 1205, 1213} or attempt == 2:
                raise


async def acknowledge_practice_help(
    owner_id, practice_id, question_id
) -> PracticeHelpView:
    async with transaction() as conn:
        row, request, scope = await practice_service.authorize_practice(
            conn, owner_id, practice_id
        )
        artifact = await practice_service.checked_practice_artifact(
            conn, row, request, scope
        )
        question = _question(artifact, question_id)
        markers = load(row["help_usage_json"], {})
        markers = dict(markers) if isinstance(markers, dict) else {}
        if markers.get(question_id) != "hints":
            markers[question_id] = "hints"
            await execute(
                "UPDATE practice_sessions SET help_usage_json=%s WHERE practice_id=%s AND owner_id=%s",
                (dump(markers), practice_id, owner_id),
                conn=conn,
            )
        # This marker shares the submission's activity lock. Existing attempts
        # keep the help state observed when their first answer won that lock.
        return PracticeHelpView(
            practice_id=practice_id,
            question_id=question_id,
            evidence_ids=list(question.citation_refs),
        )


async def mark_practice_help(owner_id: int, practice_id: str, question_id: str) -> None:
    await acknowledge_practice_help(owner_id, practice_id, question_id)


async def _submissions(conn, row):
    return await fetch_all(
        "SELECT * FROM practice_submissions WHERE owner_id=%s AND practice_id=%s "
        "ORDER BY question_id,attempt_id FOR SHARE",
        (row["owner_id"], row["practice_id"]),
        conn=conn,
    )


async def _completion(conn, row, artifact, submissions):
    saved = await fetch_one(
        "SELECT * FROM learning_activity_completions WHERE owner_id=%s "
        "AND origin_kind='practice' AND origin_id=%s FOR SHARE",
        (row["owner_id"], row["practice_id"]),
        conn=conn,
    )
    if row["completion_json"] is None:
        if saved or row["status"] == "completed" or row["completed_at"] is not None:
            raise conflict("completion_conflict", "练习完成记录不完整")
        return None, None
    try:
        receipt = PracticeCompletionReceipt.model_validate(load(row["completion_json"]))
    except (ValidationError, ValueError, TypeError) as exc:
        raise conflict("completion_conflict", "练习完成记录不完整") from exc
    ids = sorted(item["attempt_id"] for item in submissions)
    if (
        saved is None
        or row["status"] != "completed"
        or row["completed_at"] is None
        or receipt.practice_id != row["practice_id"]
        or receipt.completion_id != saved["completion_id"]
        or receipt.accepted_revision > row["revision"]
        or receipt.attempt_ids != ids
        or load(saved["attempt_ids_json"]) != ids
        or receipt.answer_set_hash != stable_hash(ids)
        or saved["answer_set_hash"] != receipt.answer_set_hash
        or (saved["space_id"], saved["scope_revision"])
        != (row["space_id"], row["scope_revision"])
        or _utc(saved["completed_at"]) != receipt.completed_at
        or _utc(row["completed_at"]) != receipt.completed_at
        or {item["question_id"] for item in submissions}
        != set(artifact.question_versions)
    ):
        raise conflict("completion_conflict", "练习完成记录与固定作答集合不一致")
    return receipt, saved


async def complete_practice(
    owner_id: int, practice_id: str, expected_revision: int
) -> PracticeCompletionReceipt:
    async with transaction() as conn:
        row, request, scope = await practice_service.authorize_practice(
            conn, owner_id, practice_id
        )
        artifact = await practice_service.checked_practice_artifact(
            conn, row, request, scope
        )
        submissions = await _submissions(conn, row)
        receipt, _ = await _completion(conn, row, artifact, submissions)
        if receipt is not None:
            return receipt
        if row["status"] != "ready":
            raise conflict("activity_unavailable", "本次练习当前不能完成")
        if row["revision"] != expected_revision:
            raise conflict("revision_conflict", "练习作答已经更新，请刷新后重试")
        if {item["question_id"] for item in submissions} != set(
            artifact.question_versions
        ):
            raise conflict("activity_incomplete", "请先完成本次练习的所有题目")
        ids = sorted(item["attempt_id"] for item in submissions)
        completed_at = _utc(now())
        completed = await events.record_completion(
            conn,
            owner_id,
            origin_kind="practice",
            origin_id=practice_id,
            attempt_ids=ids,
            completed_at=completed_at,
        )
        receipt = PracticeCompletionReceipt(
            practice_id=practice_id,
            completion_id=completed.completion_id,
            accepted_revision=row["revision"] + 1,
            answer_set_hash=completed.answer_set_hash,
            attempt_ids=ids,
            completed_at=completed_at,
        )
        await execute(
            "UPDATE practice_sessions SET status='completed',revision=revision+1,"
            "completed_at=%s,completion_json=%s WHERE practice_id=%s AND owner_id=%s",
            (completed_at.replace(tzinfo=None), dump(receipt), practice_id, owner_id),
            conn=conn,
        )
        return receipt


def _assessment_view(row):
    draft = AssessmentDraft(
        **{
            field: row[field]
            for field in AssessmentDraft.model_fields
            if field not in {"feedback", "evidence_refs", "criterion_results"}
        },
        feedback=row["feedback"] or "",
        evidence_refs=load(row["evidence_refs_json"], []),
        criterion_results=load(row["criterion_results_json"], []),
    )
    return public_assessment(
        draft,
        assessment_id=row["assessment_id"],
        attempt_id=row["attempt_id"],
        revision=row["revision"],
        created_at=_utc(row["created_at"]),
    )


async def _attempt_view(conn, origin, practice, artifact, submission, attempt):
    question = events._check_attempt(origin, attempt)
    receipt = _submission_receipt(submission, practice, artifact)
    if (attempt["question_id"], attempt["question_version"]) != (
        submission["question_id"],
        submission["question_version"],
    ):
        raise not_found()
    history = await fetch_all(
        "SELECT * FROM assessment_records WHERE attempt_id=%s AND owner_id=%s ORDER BY revision FOR SHARE",
        (attempt["attempt_id"], origin.owner_id),
        conn=conn,
    )
    for assessment in history:
        projections._check_head(origin, attempt, question, assessment)
    head_link = await fetch_one(
        "SELECT assessment_id,revision FROM learning_assessment_heads "
        "WHERE attempt_id=%s AND owner_id=%s FOR SHARE",
        (attempt["attempt_id"], origin.owner_id),
        conn=conn,
    )
    head = next(
        (
            item
            for item in history
            if head_link
            and (item["assessment_id"], item["revision"])
            == (head_link["assessment_id"], head_link["revision"])
        ),
        None,
    )
    if bool(history) != bool(head) or (
        receipt.assessment_id
        and receipt.assessment_id not in {item["assessment_id"] for item in history}
    ):
        raise conflict("assessment_identity_conflict", "评分当前版本不完整")
    grading = await fetch_one(
        "SELECT * FROM practice_grading_requests WHERE attempt_id=%s AND owner_id=%s FOR SHARE",
        (attempt["attempt_id"], origin.owner_id),
        conn=conn,
    )
    if (grading is None) != (receipt.grading_request_id is None) or (
        grading and grading["grading_request_id"] != receipt.grading_request_id
    ):
        raise not_found()
    # Existing jobs are deliberately not locked after the activity. Grading
    # request status is updated while holding that same activity lock by P04.
    grading_status = None
    if grading:
        grading_status = grading["status"]
        if grading_status not in {
            "pending",
            "running",
            "completed",
            "failed",
            "cancelled",
        }:
            grading_status = "completed" if head else "pending"
    annotations = await fetch_all(
        "SELECT * FROM learning_annotations WHERE owner_id=%s AND attempt_id=%s "
        "AND kind='self_review' ORDER BY created_at,annotation_id FOR SHARE",
        (origin.owner_id, attempt["attempt_id"]),
        conn=conn,
    )
    self_reviews = []
    for annotation in annotations:
        payload = load(annotation["payload_json"], {})
        self_reviews.append(
            PracticeSelfReviewView(
                annotation_id=annotation["annotation_id"],
                self_rating=payload["self_rating"],
                notes=payload.get("notes", ""),
                created_at=_utc(annotation["created_at"]),
            )
        )
    return PracticeAttemptView(
        practice_id=practice["practice_id"],
        question_id=attempt["question_id"],
        attempt_id=attempt["attempt_id"],
        question_version=attempt["question_version"],
        answer=_ANSWER.validate_python(load(attempt["answer_json"])),
        duration_ms=attempt["duration_ms"],
        help_usage=attempt["help_usage"],
        receipt=receipt,
        current_assessment=_assessment_view(head) if head else None,
        assessment_history=[_assessment_view(item) for item in history],
        self_reviews=self_reviews,
        grading_status=grading_status,
        active_task_id=grading["active_task_id"] if grading else None,
        grading_revision=grading["revision"] if grading else 0,
        created_at=_utc(attempt["created_at"]),
    ), head


async def read_practice_progress(conn, row, artifact) -> dict:
    """Only saved answers and public assessments enter a practice GET response."""
    origin = await events._locked_origin(
        conn, row["owner_id"], "practice", row["practice_id"]
    )
    submissions = await _submissions(conn, row)
    attempts = await fetch_all(
        "SELECT * FROM learning_attempts WHERE owner_id=%s AND origin_kind='practice' "
        "AND origin_id=%s ORDER BY question_id,attempt_id FOR SHARE",
        (row["owner_id"], row["practice_id"]),
        conn=conn,
    )
    by_id = {item["attempt_id"]: item for item in attempts}
    if set(by_id) != {item["attempt_id"] for item in submissions}:
        raise not_found()
    views, heads = [], {}
    for submission in submissions:
        attempt = by_id[submission["attempt_id"]]
        view, head = await _attempt_view(
            conn, origin, row, artifact, submission, attempt
        )
        views.append(view)
        heads[attempt["attempt_id"]] = head
    receipt, completion = await _completion(conn, row, artifact, submissions)
    confirmed_ids = {
        view.attempt_id
        for view in views
        if view.current_assessment is not None
        and view.current_assessment.status == "graded"
        and view.current_assessment.confirmation == "confirmed"
    }
    confirmed = len(confirmed_ids)
    pending = sum(
        view.attempt_id not in confirmed_ids
        and view.grading_status in {"pending", "running"}
        for view in views
    )
    projection_status = "not_ready"
    if completion:
        projections._check_completion(origin, completion, attempts)
        projection_status = "pending"
        if confirmed == len(attempts):
            assessment_set_hash = stable_hash(
                {
                    "completion_id": completion["completion_id"],
                    "answer_set_hash": completion["answer_set_hash"],
                    "heads": [
                        projections._head_identity(
                            attempt, heads[attempt["attempt_id"]]
                        )
                        for attempt in attempts
                    ],
                }
            )
            projected = await fetch_one(
                "SELECT projection_json FROM learning_projection_receipts WHERE owner_id=%s "
                "AND origin_kind='practice' AND origin_id=%s AND completion_id=%s "
                "AND assessment_set_hash=%s AND rule_version=%s FOR SHARE",
                (
                    row["owner_id"],
                    row["practice_id"],
                    completion["completion_id"],
                    assessment_set_hash,
                    RULE_VERSION,
                ),
                conn=conn,
            )
            if (
                projected
                and load(projected["projection_json"], {}).get("status") == "projected"
            ):
                projection_status = "applied"
            else:
                failed = await fetch_one(
                    "SELECT 1 AS failed FROM learning_outbox o JOIN quiz_tasks j "
                    "ON j.task_id=o.task_id AND j.user_id=o.owner_id WHERE o.owner_id=%s "
                    "AND o.origin_kind='practice' AND o.origin_id=%s AND o.processed_at IS NULL "
                    "AND j.status IN ('failed','cancelled') LIMIT 1",
                    (row["owner_id"], row["practice_id"]),
                    conn=conn,
                )
                if failed:
                    projection_status = "failed"
    return {
        "submissions": views,
        "submitted_count": len(views),
        "confirmed_count": confirmed,
        "pending_grading_count": pending,
        "needs_review_count": len(views) - confirmed - pending,
        "completed_at": receipt.completed_at if receipt else None,
        "completion": receipt,
        "projection_status": projection_status,
    }


async def practice_attempt_view(
    conn, owner_id: int, attempt_id: str
) -> PracticeAttemptView:
    """Connection-aware reader for task polling after the caller's job lock."""
    submission = await fetch_one(
        "SELECT practice_id FROM practice_submissions WHERE owner_id=%s AND attempt_id=%s",
        (owner_id, attempt_id),
        conn=conn,
    )
    if submission is None:
        raise not_found()
    row, request, scope = await practice_service.authorize_practice(
        conn, owner_id, submission["practice_id"]
    )
    artifact = await practice_service.checked_practice_artifact(
        conn, row, request, scope
    )
    progress = await read_practice_progress(conn, row, artifact)
    return next(
        view for view in progress["submissions"] if view.attempt_id == attempt_id
    )


async def get_practice_attempt(owner_id: int, attempt_id: str) -> PracticeAttemptView:
    async with transaction() as conn:
        return await practice_attempt_view(conn, owner_id, attempt_id)
