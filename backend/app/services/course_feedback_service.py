"""Course feedback issues, append-only corrections and authorized regrades (B03).

没有理解、内容纠错和评分异议分别定位到课时段落、自检回答、客观题或
课程应用回答。教学解释、个人纠正与权威判分修正状态分开：普通用户
只能产生 provisional 记录；confirmed 判分只能由 owner+evaluator 复核产生。
"""

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, load, now, uid
from app.models.course_feedback import (
    Confirmation,
    CourseApplicationRegrade,
    CourseCorrectionCreate,
    CourseCorrectionReview,
    CourseCorrectionView,
    CourseFeedbackCreate,
    CourseFeedbackUpdate,
    CourseFeedbackView,
)
from app.services import (
    course_application_service,
    course_assessment_service,
    course_read,
    course_self_check_service,
)


def correction_effect(*, provenance: str, confirmation: str, target_kind: str) -> str:
    """个人/模型纠正永远只是注释；正式效力只来自有权限的人工复核。"""
    if provenance != "human_reviewer" or confirmation != "confirmed":
        return "annotation_only"
    if target_kind == "course_assessment":
        return "supersede_assessment"
    if target_kind == "quiz":
        return "request_new_check"
    return "prepare_content_revision"


async def _existing(owner, key, request_hash, *, conn=None):
    if not key:
        raise AppError(422, "idempotency_required", "需要有效 Idempotency-Key")
    row = await fetch_one(
        "SELECT * FROM learning_course_feedback WHERE owner_id=%s AND idempotency_key=%s",
        (owner, key),
        conn=conn,
    )
    if row and row["request_hash"] != request_hash:
        raise conflict("idempotency_conflict", "相同操作标识已用于不同请求")
    return row


async def _lesson_target(owner, course_id, target, *, conn):
    lesson = await course_read.owned_lesson(owner, course_id, target.lesson_id, conn=conn)
    payload = load(lesson["content_json"], {}).get("payload", {})
    if int(lesson["content_version"]) != target.content_version:
        raise conflict("revision_conflict", "课时内容版本已更新，请刷新后重新定位")
    blocks = payload.get("blocks", [])
    if target.block_index >= len(blocks):
        raise conflict("feedback_target_out_of_range", "引用的段落已不存在，请刷新后重试")
    return {
        "target_kind": "lesson",
        "lesson_id": target.lesson_id,
        "content_version": target.content_version,
        "block_index": target.block_index,
    }


async def _self_check_target(owner, course_id, target, *, conn):
    await course_self_check_service.owned_check_attempt(
        owner, course_id, target.lesson_id, target.check_attempt_id, conn=conn
    )
    return {
        "target_kind": "self_check",
        "lesson_id": target.lesson_id,
        "content_version": target.content_version,
        "check_attempt_id": target.check_attempt_id,
    }


async def _quiz_target(owner, course_id, target, *, conn):
    context = await course_read.course_context_for_quiz(owner, target.quiz_id, conn=conn)
    if not context or context["course_id"] != course_id:
        raise not_found()
    quiz = await fetch_one(
        "SELECT questions_json FROM quiz_sessions WHERE quiz_id=%s AND user_id=%s",
        (target.quiz_id, owner),
        conn=conn,
    )
    question_ids = {q.get("id") for q in load(quiz["questions_json"], [])} if quiz else set()
    if target.question_id not in question_ids:
        raise not_found()
    return {
        "target_kind": "quiz",
        "quiz_id": target.quiz_id,
        "question_id": target.question_id,
    }


async def _assessment_target(owner, course_id, target, *, conn):
    await course_assessment_service.owned_assessment(
        owner, course_id, target.course_assessment_id, conn=conn
    )
    await course_application_service.owned_attempt(
        owner, course_id, target.course_assessment_id, target.attempt_id, conn=conn
    )
    return {
        "target_kind": "course_assessment",
        "course_assessment_id": target.course_assessment_id,
        "attempt_id": target.attempt_id,
    }


_RESOLVERS = {
    "lesson": _lesson_target,
    "self_check": _self_check_target,
    "quiz": _quiz_target,
    "course_assessment": _assessment_target,
}


async def _resolve_target(owner, course_id, target, *, conn):
    return await _RESOLVERS[target.kind](owner, course_id, target, conn=conn)


def _view(row) -> CourseFeedbackView:
    target = {
        "lesson": {
            "kind": "lesson",
            "lesson_id": row["lesson_id"],
            "content_version": row["content_version"],
            "block_index": row["block_index"],
        },
        "self_check": {
            "kind": "self_check",
            "lesson_id": row["lesson_id"],
            "content_version": row["content_version"],
            "check_attempt_id": row["check_attempt_id"],
        },
        "quiz": {
            "kind": "quiz",
            "quiz_id": row["quiz_id"],
            "question_id": row["question_id"],
        },
        "course_assessment": {
            "kind": "course_assessment",
            "course_assessment_id": row["course_assessment_id"],
            "attempt_id": row["attempt_id"],
        },
    }[row["target_kind"]]
    return CourseFeedbackView(
        feedback_id=row["feedback_id"],
        course_id=row["course_id"],
        issue_kind=row["issue_kind"],
        target=target,
        comment=row["comment"],
        status=row["status"],
        revision=row["revision"],
        tutor_turn_id=row["tutor_turn_id"],
        quiz_feedback_id=row["quiz_feedback_id"],
        created_at=row["created_at"].isoformat(),
    )


async def _with_corrections(row, *, conn=None) -> CourseFeedbackView:
    view = _view(row)
    rows = await fetch_all(
        "SELECT * FROM learning_course_corrections WHERE feedback_id=%s AND owner_id=%s "
        "ORDER BY created_at,correction_id",
        (row["feedback_id"], row["owner_id"]),
        conn=conn,
    )
    view.corrections = [
        CourseCorrectionView(
            correction_id=item["correction_id"],
            feedback_id=row["feedback_id"],
            supersedes_correction_id=item["supersedes_correction_id"],
            text=item["body"],
            source_refs=load(item["source_refs"], []),
            provenance=item["provenance"],
            confirmation=item["confirmation"],
            created_at=item["created_at"].isoformat(),
        )
        for item in rows
    ]
    return view


async def create_course_feedback(actor, course_id, body: CourseFeedbackCreate, key):
    owner = actor.owner_id
    request_hash = digest(dump({"course_id": course_id, **body.model_dump(mode="json")}))
    async with transaction() as conn:
        row = await _existing(owner, key, request_hash, conn=conn)
        if row is None:
            course = await course_read.owned_course(owner, course_id, conn=conn)
            await course_read.authorize_course(course, conn=conn)
            target_cols = await _resolve_target(owner, course_id, body.target, conn=conn)
            quiz_feedback_id = None
            if body.issue_kind == "grading_review" and body.target.kind == "quiz":
                from app.models.feedback import FeedbackCreate
                from app.services import feedback_service

                quiz_feedback = await feedback_service.create_feedback(
                    actor,
                    body.target.quiz_id,
                    FeedbackCreate(
                        question_id=body.target.question_id,
                        reason="other",
                        comment=body.comment,
                        allow_evaluation_use=body.allow_evaluation_use,
                    ),
                )
                quiz_feedback_id = quiz_feedback["feedback_id"]
            feedback_id = uid("cfb_")
            await execute(
                "INSERT INTO learning_course_feedback(feedback_id,course_id,owner_id,issue_kind,"
                "target_kind,lesson_id,content_version,block_index,check_attempt_id,quiz_id,"
                "question_id,course_assessment_id,attempt_id,comment,allow_evaluation_use,"
                "quiz_feedback_id,idempotency_key,request_hash) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    feedback_id,
                    course_id,
                    owner,
                    body.issue_kind,
                    target_cols["target_kind"],
                    target_cols.get("lesson_id"),
                    target_cols.get("content_version"),
                    target_cols.get("block_index"),
                    target_cols.get("check_attempt_id"),
                    target_cols.get("quiz_id"),
                    target_cols.get("question_id"),
                    target_cols.get("course_assessment_id"),
                    target_cols.get("attempt_id"),
                    body.comment,
                    body.allow_evaluation_use,
                    quiz_feedback_id,
                    key,
                    request_hash,
                ),
                conn=conn,
            )
            row = await fetch_one(
                "SELECT * FROM learning_course_feedback WHERE feedback_id=%s AND owner_id=%s",
                (feedback_id, owner),
                conn=conn,
            )
    return await _with_corrections(row, conn=conn)


async def list_course_feedback(
    owner,
    course_id,
    *,
    lesson_id=None,
    check_attempt_id=None,
    course_assessment_id=None,
):
    clauses = ["owner_id=%s", "course_id=%s", "revoked_at IS NULL"]
    params: list = [owner, course_id]
    if lesson_id is not None:
        clauses.append("lesson_id=%s")
        params.append(lesson_id)
    if check_attempt_id is not None:
        clauses.append("check_attempt_id=%s")
        params.append(check_attempt_id)
    if course_assessment_id is not None:
        clauses.append("course_assessment_id=%s")
        params.append(course_assessment_id)
    where = " AND ".join(clauses)
    rows = await fetch_all(
        f"SELECT * FROM learning_course_feedback WHERE {where} ORDER BY created_at,feedback_id",
        tuple(params),
    )
    items = [await _with_corrections(row) for row in rows]
    return {"items": items, "total": len(items)}


async def _owned_feedback(owner, course_id, feedback_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM learning_course_feedback WHERE feedback_id=%s AND course_id=%s "
        "AND owner_id=%s AND revoked_at IS NULL" + (" FOR UPDATE" if lock else ""),
        (feedback_id, course_id, owner),
        conn=conn,
    )
    if row is None:
        raise not_found()
    return row


async def update_course_feedback(owner, course_id, feedback_id, body: CourseFeedbackUpdate):
    async with transaction() as conn:
        row = await _owned_feedback(owner, course_id, feedback_id, conn=conn, lock=True)
        if row["revision"] != body.expected_revision:
            raise conflict("revision_conflict", "反馈状态已更新，请刷新后重试")
        if row["status"] == "rejected":
            raise conflict("feedback_closed", "该反馈已被复核退回，不能再修改状态")
        await execute(
            "UPDATE learning_course_feedback SET status=%s,revision=revision+1 "
            "WHERE feedback_id=%s AND owner_id=%s",
            (body.status, feedback_id, owner),
            conn=conn,
        )
        row = await _owned_feedback(owner, course_id, feedback_id, conn=conn)
    return await _with_corrections(row)


async def create_correction(
    owner, course_id, feedback_id, body: CourseCorrectionCreate, key
) -> CourseCorrectionView:
    request_hash = digest(
        dump({"feedback_id": feedback_id, **body.model_dump(mode="json")})
    )
    async with transaction() as conn:
        existing = await fetch_one(
            "SELECT correction_id FROM learning_course_corrections "
            "WHERE owner_id=%s AND request_hash=%s ORDER BY created_at LIMIT 1",
            (owner, request_hash),
            conn=conn,
        )
        if existing:
            return await _owned_correction(existing["correction_id"], owner, conn=conn)
        feedback = await _owned_feedback(owner, course_id, feedback_id, conn=conn, lock=True)
        if feedback["revision"] != body.expected_revision:
            raise conflict("revision_conflict", "反馈状态已更新，请刷新后重试")
        if body.supersedes_correction_id:
            superseded = await _owned_correction(
                body.supersedes_correction_id, owner, conn=conn
            )
            if superseded["feedback_id"] != feedback_id:
                raise not_found()
        correction_id = uid("cfc_")
        await execute(
            "INSERT INTO learning_course_corrections(correction_id,feedback_id,course_id,"
            "owner_id,supersedes_correction_id,body,source_refs,provenance,confirmation,"
            "request_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,'learner_note','provisional',%s)",
            (
                correction_id,
                feedback_id,
                course_id,
                owner,
                body.supersedes_correction_id,
                body.text,
                dump(body.source_refs),
                request_hash,
            ),
            conn=conn,
        )
    return await _owned_correction(correction_id, owner)


async def _owned_correction(correction_id, owner, *, conn=None):
    row = await fetch_one(
        "SELECT * FROM learning_course_corrections WHERE correction_id=%s AND owner_id=%s",
        (correction_id, owner),
        conn=conn,
    )
    if row is None:
        raise not_found()
    return CourseCorrectionView(
        correction_id=row["correction_id"],
        feedback_id=row["feedback_id"],
        supersedes_correction_id=row["supersedes_correction_id"],
        text=row["body"],
        source_refs=load(row["source_refs"], []),
        provenance=row["provenance"],
        confirmation=row["confirmation"],
        created_at=row["created_at"].isoformat(),
    )


async def review_correction(actor, course_id, feedback_id, body: CourseCorrectionReview):
    """owner + evaluator 确认或退回内容纠正；追加新记录，不修改旧记录。"""
    owner = actor.owner_id
    async with transaction() as conn:
        feedback = await _owned_feedback(owner, course_id, feedback_id, conn=conn, lock=True)
        if feedback["revision"] != body.expected_revision:
            raise conflict("revision_conflict", "反馈状态已更新，请刷新后重试")
        latest = await fetch_one(
            "SELECT * FROM learning_course_corrections WHERE feedback_id=%s AND owner_id=%s "
            "ORDER BY created_at DESC,correction_id DESC LIMIT 1",
            (feedback_id, owner),
            conn=conn,
        )
        correction_id = uid("cfc_")
        review_hash = digest(dump([feedback_id, body.model_dump(mode="json"), now()]))
        if body.decision == "confirmed":
            confirmation: Confirmation = "confirmed"
            await execute(
                "INSERT INTO learning_course_corrections(correction_id,feedback_id,course_id,"
                "owner_id,supersedes_correction_id,body,source_refs,provenance,confirmation,"
                "request_hash) VALUES(%s,%s,%s,%s,%s,%s,%s,'human_reviewer','confirmed',%s)",
                (
                    correction_id,
                    feedback_id,
                    course_id,
                    owner,
                    latest["correction_id"] if latest else None,
                    body.note or (latest["body"] if latest else ""),
                    latest["source_refs"] if latest else dump([]),
                    review_hash,
                ),
                conn=conn,
            )
        else:
            confirmation = "provisional"
            await execute(
                "INSERT INTO learning_course_corrections(correction_id,feedback_id,course_id,"
                "owner_id,supersedes_correction_id,body,source_refs,provenance,confirmation,"
                "request_hash) VALUES(%s,%s,%s,%s,NULL,%s,%s,'human_reviewer','provisional',%s)",
                (correction_id, feedback_id, course_id, owner, body.note, dump([]), review_hash),
                conn=conn,
            )
            await execute(
                "UPDATE learning_course_feedback SET status='rejected',revision=revision+1 "
                "WHERE feedback_id=%s AND owner_id=%s",
                (feedback_id, owner),
                conn=conn,
            )
    return await _owned_correction(correction_id, owner)


async def review_application_attempt(
    actor, course_id, course_assessment_id, attempt_id, body: CourseApplicationRegrade
):
    """正式复核：固定 rubric 下追加 human 判分头并 supersedes 旧头，不改原答卷。"""
    owner = actor.owner_id
    async with transaction() as conn:
        await course_assessment_service.owned_assessment(
            owner, course_id, course_assessment_id, conn=conn, lock=True
        )
        attempt = await course_application_service.owned_attempt(
            owner, course_id, course_assessment_id, attempt_id, conn=conn, lock=True
        )
        current = None
        if attempt["latest_assessment_id"]:
            current = await fetch_one(
                "SELECT * FROM learning_course_application_assessments "
                "WHERE assessment_id=%s AND attempt_id=%s AND owner_id=%s",
                (attempt["latest_assessment_id"], attempt_id, owner),
                conn=conn,
            )
        if current is None:
            raise conflict("regrade_baseline_missing", "该回答暂无可复核的判分记录")
        if current["confirmation"] == "confirmed":
            raise conflict("regrade_already_confirmed", "已有确认判分，不能再复核")
        if attempt["revision"] != body.expected_revision:
            raise conflict("revision_conflict", "该回答已有更新，请刷新后重试")
        if current["assessment_id"] != body.expected_assessment_id:
            raise conflict("revision_conflict", "判分头已更新，请刷新后重试")
        status = "graded" if body.status == "graded" and body.score is not None else "needs_review"
        assessment_id = uid("cag_")
        await execute(
            "INSERT INTO learning_course_application_assessments(assessment_id,attempt_id,"
            "course_assessment_id,course_id,owner_id,question_version,rubric_hash,status,"
            "confirmation,source,score,feedback_json,supersedes_assessment_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'confirmed','human',%s,%s,%s)",
            (
                assessment_id,
                attempt_id,
                course_assessment_id,
                course_id,
                owner,
                current["question_version"],
                current["rubric_hash"],
                status,
                body.score,
                dump({"comment": body.comment, "reviewer_id": actor.owner_id}),
                current["assessment_id"],
            ),
            conn=conn,
        )
        await execute(
            "UPDATE learning_course_application_attempts SET latest_assessment_id=%s "
            "WHERE attempt_id=%s AND owner_id=%s",
            (assessment_id, attempt_id, owner),
            conn=conn,
        )
    return {
        "assessment_id": assessment_id,
        "attempt_id": attempt_id,
        "status": status,
        "confirmation": "confirmed",
        "supersedes_assessment_id": current["assessment_id"],
        "effect": correction_effect(
            provenance="human_reviewer", confirmation="confirmed", target_kind="course_assessment"
        ),
    }


async def purge_course_feedback(conn, owner, course_id):
    """课程删除/资料撤销时清除反馈与纠正正文，保留身份便于审计。"""
    await execute(
        "UPDATE learning_course_feedback SET comment='',revoked_at=%s "
        "WHERE course_id=%s AND owner_id=%s AND revoked_at IS NULL",
        (now(), course_id, owner),
        conn=conn,
    )
    await execute(
        "UPDATE learning_course_corrections c JOIN learning_course_feedback f "
        "ON f.feedback_id=c.feedback_id AND f.owner_id=c.owner_id "
        "SET c.body='' WHERE f.course_id=%s AND c.owner_id=%s",
        (course_id, owner),
        conn=conn,
    )
