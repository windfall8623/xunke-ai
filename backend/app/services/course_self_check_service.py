"""Immutable classroom self checks; saving never calls a model or grading service."""

from pymysql import IntegrityError

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load, uid
from app.models.course_tutor import CourseSelfCheckView
from app.services import course_read
from app.services.course_service import require_enabled
from app.services.course_tutor_service import authorized_lesson, check_lesson_version, latest_turn_for_attempt
from app.teaching.contracts import LessonCheck


def lesson_check(lesson, check_ref):
    checks = (load(lesson["content_json"], {}).get("payload") or {}).get("checks", [])
    matches = [item for item in checks if item.get("check_ref") == check_ref]
    if not matches:
        raise not_found()
    if len(matches) != 1:
        raise conflict("course_check_ambiguous", "本课自检标识不唯一，暂时无法保存")
    return LessonCheck.model_validate(matches[0])


def validate_check_answer(check, answer):
    if check.question_type in {"single", "multiple", "judge"}:
        keys = [option.key for option in check.options]
        if not keys or len(keys) != len(set(keys)):
            raise conflict("course_check_options_missing", "本题缺少有效选项，暂时无法保存")
        if check.question_type == "multiple":
            valid = (isinstance(answer, list) and 1 <= len(answer) <= len(keys)
                     and len(answer) == len(set(answer)) and set(answer) <= set(keys))
        else:
            valid = isinstance(answer, str) and answer in keys
        if not valid:
            raise AppError(422, "course_check_answer_invalid", "请只提交本题允许的选项")
    elif not isinstance(answer, str) or not answer.strip() or len(answer) > 2000:
        raise AppError(422, "course_check_answer_invalid", "请填写不超过 2000 字的回答")
    return answer


async def owned_check_attempt(owner, course_id, lesson_id, attempt_id, *, conn=None):
    row = await fetch_one(
        "SELECT * FROM learning_course_check_attempts WHERE attempt_id=%s AND owner_id=%s "
        "AND course_id=%s AND lesson_id=%s", (attempt_id, owner, course_id, lesson_id), conn=conn,
    )
    if not row:
        raise not_found()
    if row["revoked_at"] is not None or row["answer_json"] is None:
        raise AppError(404, "source_revoked", "自检回答关联资料已失效")
    return row


async def check_attempt_context(owner, course_id, lesson_id, attempt_id, lesson, *, conn=None):
    row = await owned_check_attempt(owner, course_id, lesson_id, attempt_id, conn=conn)
    check_lesson_version(lesson, row["content_version"])
    check = lesson_check(lesson, row["check_ref"])
    answer = validate_check_answer(check, load(row["answer_json"]))
    return dict(check=check.model_dump(mode="json"), answer=answer)


async def _view(row, *, conn=None):
    latest = await latest_turn_for_attempt(
        row["owner_id"], row["course_id"], row["lesson_id"], row["content_version"], row["attempt_id"], conn=conn
    )
    return CourseSelfCheckView(
        attempt_id=row["attempt_id"], course_id=row["course_id"], lesson_id=row["lesson_id"],
        content_version=row["content_version"], check_ref=row["check_ref"], answer=load(row["answer_json"]),
        saved_at=iso(row["saved_at"]), latest_tutor_turn=latest,
    ).model_dump(mode="json")


async def _existing(owner, key, request_hash, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM learning_course_check_attempts WHERE owner_id=%s AND idempotency_key=%s"
        + (" FOR UPDATE" if lock else ""), (owner, key), conn=conn,
    )
    if row and row["request_hash"] != request_hash:
        raise conflict("idempotency_conflict", "相同操作标识已用于不同请求")
    return row


async def save_check_attempt(actor, course_id, lesson_id, body, key):
    require_enabled()
    owner = actor.owner_id
    if not key or len(key) > 128:
        raise AppError(422, "idempotency_required", "需要有效 Idempotency-Key")
    _, lesson, _ = await authorized_lesson(owner, course_id, lesson_id, body.expected_content_version)
    validate_check_answer(lesson_check(lesson, body.check_ref), body.answer)
    request_hash = digest(dump(dict(course_id=course_id, lesson_id=lesson_id, **body.model_dump(mode="json"))))
    async with transaction() as conn:
        course, lesson, _ = await authorized_lesson(
            owner, course_id, lesson_id, body.expected_content_version, conn=conn, lock=True
        )
        validate_check_answer(lesson_check(lesson, body.check_ref), body.answer)
        row = await _existing(owner, key, request_hash, conn=conn)
        if row is None:
            attempt_id = uid("check")
            try:
                await execute(
                    "INSERT INTO learning_course_check_attempts(attempt_id,course_id,lesson_id,owner_id,"
                    "content_version,check_ref,answer_json,idempotency_key,request_hash) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (attempt_id, course_id, lesson_id, owner, body.expected_content_version,
                     body.check_ref, dump(body.answer), key, request_hash), conn=conn,
                )
            except IntegrityError:
                row = await _existing(owner, key, request_hash, conn=conn, lock=True)
                if row is None:
                    raise
            else:
                row = await owned_check_attempt(owner, course_id, lesson_id, attempt_id, conn=conn)
        if row["revoked_at"] is not None or row["answer_json"] is None:
            raise AppError(404, "source_revoked", "自检回答关联资料已失效")
        result = await _view(row, conn=conn)
        await course_read.authorize_course(course, conn=conn)
    return result


async def list_check_attempts(owner, course_id, lesson_id, content_version):
    course, _, _ = await authorized_lesson(owner, course_id, lesson_id, content_version)
    rows = await fetch_all(
        "SELECT * FROM learning_course_check_attempts WHERE owner_id=%s AND course_id=%s "
        "AND lesson_id=%s AND content_version=%s AND revoked_at IS NULL ORDER BY saved_at,attempt_id",
        (owner, course_id, lesson_id, content_version),
    )
    result = [await _view(row) for row in rows]
    await course_read.authorize_course(course)
    return result
