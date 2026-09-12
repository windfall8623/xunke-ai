"""Lesson review outbox, deterministic scheduling and durable quiz bindings.

No grades are copied here: each event references an actual Quiz settlement.
The owner worker consumes events; reading a course or today's suggestions never
creates an event, advances a schedule or starts a model task.
"""

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load, uid
from app.learning.contracts import ConceptState, IanaTimezone, LearningOutcome
from app.learning.review_rules import RULE_VERSION, next_schedule
from app.models.course_review import CourseReviewStart, CourseReviewView
from app.rag.contracts import ResolvedScope
from app.services import course_quiz_service as quizzes
from app.services import course_read, job_service, learning_concept_service, quiz_service

_TIMEZONE = TypeAdapter(IanaTimezone)
_TERMINAL = {"completed", "superseded", "source_revoked"}


def _aware(value):
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _sql_time(value):
    return value.astimezone(UTC).replace(tzinfo=None) if value is not None else None


def _require_transaction(conn):
    if conn is None or not conn.get_transaction_status():
        raise ValueError("Course review writes require the caller's transaction")


async def append_settlement_event(conn, owner, quiz_id):
    """Append exactly once in complete_quiz's successful settlement transaction."""
    _require_transaction(conn)
    row = await fetch_one(
        "SELECT link.link_id,link.course_id,link.lesson_id,link.content_version,"
        "quiz.settled_at,course.spec_json "
        "FROM learning_course_quiz_links link "
        "JOIN quiz_tasks task ON task.task_id=link.task_id AND task.user_id=link.owner_id "
        "AND task.kind='quiz' AND task.mode='production' AND task.status='completed' "
        "JOIN quiz_sessions quiz ON quiz.quiz_id=task.quiz_id AND quiz.user_id=link.owner_id "
        "AND quiz.origin_task_id=task.task_id AND quiz.status='settled' "
        "JOIN learning_courses course ON course.course_id=link.course_id AND course.owner_id=link.owner_id "
        "WHERE link.owner_id=%s AND quiz.quiz_id=%s AND quiz.settled_at IS NOT NULL",
        (owner, quiz_id), conn=conn,
    )
    if row is None:
        return
    timezone = _TIMEZONE.validate_python(load(row["spec_json"], {}).get("timezone", "Asia/Shanghai"))
    await execute(
        "INSERT INTO learning_course_review_events "
        "(event_id,owner_id,course_id,lesson_id,content_version,link_id,quiz_id,settled_at,timezone,rule_version) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE event_id=event_id",
        (uid("cre"), owner, row["course_id"], row["lesson_id"], row["content_version"],
         row["link_id"], quiz_id, row["settled_at"], timezone, RULE_VERSION),
        conn=conn,
    )


async def _finish_event(conn, event, reason=None):
    await execute(
        "UPDATE learning_course_review_events SET processed_at=UTC_TIMESTAMP(6),skipped_reason=%s "
        "WHERE event_id=%s AND owner_id=%s AND processed_at IS NULL",
        (reason, event["event_id"], event["owner_id"]), conn=conn,
    )


def _state(row):
    if row is None:
        return ConceptState()
    return ConceptState(
        stage=row["stage"], revision=row["revision"],
        last_activity_local_date=row["last_activity_local_date"],
        last_success_local_date=row["last_success_local_date"],
        last_question_versions=load(row["last_question_versions_json"], []),
        seen_question_versions=load(row["seen_question_versions_json"], []),
        due_at=_aware(row["due_at"]),
    )


async def _consume_event(preview):
    async with transaction() as conn:
        owner, course_id, lesson_id = preview["owner_id"], preview["course_id"], preview["lesson_id"]
        # Serialize the lesson before the event/state. Settlement itself does
        # not take these locks: it only appends a small immutable outbox fact.
        course = await course_read.owned_course(owner, course_id, conn=conn, lock=True)
        lesson = await course_read.owned_lesson(owner, course_id, lesson_id, conn=conn, lock=True)
        event = await fetch_one(
            "SELECT * FROM learning_course_review_events WHERE event_id=%s AND owner_id=%s FOR UPDATE",
            (preview["event_id"], owner), conn=conn,
        )
        if event is None or event["processed_at"] is not None:
            return 0
        if event["rule_version"] != RULE_VERSION:
            raise RuntimeError("Unsupported frozen course review rule version")
        try:
            scope = await course_read.authorize_course(course, conn=conn)
        except AppError as exc:
            if exc.code != "source_revoked":
                raise
            await _finish_event(conn, event, "source_revoked")
            return 1
        if lesson["content_version"] != event["content_version"]:
            await _finish_event(conn, event, "content_version_changed")
            return 1
        if (
            course["status"] not in {"ready", "partial"}
            or lesson["status"] != "ready" or not lesson["content_json"]
        ):
            await _finish_event(conn, event, "lesson_unavailable")
            return 1
        quiz = await fetch_one(
            "SELECT quiz.* FROM quiz_sessions quiz "
            "JOIN quiz_tasks task ON task.task_id=quiz.origin_task_id AND task.quiz_id=quiz.quiz_id "
            "AND task.user_id=quiz.user_id AND task.kind='quiz' AND task.mode='production' AND task.status='completed' "
            "JOIN learning_course_quiz_links link ON link.task_id=task.task_id AND link.owner_id=task.user_id "
            "WHERE quiz.quiz_id=%s AND quiz.user_id=%s AND link.link_id=%s "
            "AND link.course_id=%s AND link.lesson_id=%s AND link.content_version=%s",
            (event["quiz_id"], owner, event["link_id"], course_id, lesson_id, event["content_version"]),
            conn=conn,
        )
        if quiz is None or quiz["status"] != "settled" or quiz["settled_at"] != event["settled_at"]:
            raise conflict("course_review_settlement_changed", "复习结算记录不完整")
        if (
            quiz["source_status"] == "source_revoked"
            or ResolvedScope.model_validate(load(quiz["source_scope_json"])) != scope
            or quiz["source_policy"] != course["source_policy"]
        ):
            await _finish_event(conn, event, "source_revoked")
            return 1
        # Even a late backfilled event still completes its own real batch. It
        # must not, however, replace a schedule based on a newer settlement.
        await execute(
            "UPDATE learning_course_reviews SET status='completed',is_current=NULL,completed_at=%s,"
            "revision=revision+1,updated_at=UTC_TIMESTAMP(6) "
            "WHERE owner_id=%s AND active_link_id=%s AND completed_at IS NULL AND status<>'source_revoked'",
            (event["settled_at"], owner, event["link_id"]), conn=conn,
        )
        previous = await fetch_one(
            "SELECT * FROM learning_course_review_states "
            "WHERE owner_id=%s AND lesson_id=%s AND content_version=%s FOR UPDATE",
            (owner, lesson_id, event["content_version"]), conn=conn,
        )
        if previous and previous["last_settled_at"] and (
            event["settled_at"], event["quiz_id"]
        ) <= (previous["last_settled_at"], previous["last_quiz_id"]):
            # A late historical backfill must not rewind a newer real result.
            await _finish_event(conn, event, "older_settlement")
            return 1
        versions = await learning_concept_service._checked_quiz_questions(conn, owner, quiz, scope)
        answers = await fetch_all(
            "SELECT question_id,is_correct FROM quiz_answers WHERE quiz_id=%s AND user_id=%s",
            (event["quiz_id"], owner), conn=conn,
        )
        if not versions or {answer["question_id"] for answer in answers} != set(versions):
            raise conflict("course_review_settlement_changed", "复习必须引用完整的已结算作答")
        state = _state(previous)
        outcome = LearningOutcome(
            status="graded", confirmation="confirmed",
            score=Decimal(sum(bool(answer["is_correct"]) for answer in answers)) / Decimal(len(answers)),
            help_usage="unknown", independent_eligible=False,
            question_versions=sorted({item[0] for item in versions.values()}),
        )
        settled_at = _aware(event["settled_at"])
        decision = next_schedule(state, outcome, settled_at, event["timezone"])
        if decision.due_at is None:
            raise RuntimeError("Confirmed course settlement must produce a review due time")
        schedule_seq = (previous["schedule_seq"] if previous else 0) + 1
        activity_date = settled_at.astimezone(ZoneInfo(event["timezone"])).date()
        seen = sorted(set(state.seen_question_versions) | set(outcome.question_versions))
        await execute(
            "INSERT INTO learning_course_review_states "
            "(owner_id,course_id,lesson_id,content_version,schedule_seq,revision,stage,"
            "last_activity_local_date,last_question_versions_json,seen_question_versions_json,"
            "due_at,last_settled_at,last_quiz_id,last_event_id,rule_version) "
            "VALUES(%s,%s,%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE schedule_seq=VALUES(schedule_seq),revision=revision+1,"
            "stage=VALUES(stage),last_activity_local_date=VALUES(last_activity_local_date),"
            "last_question_versions_json=VALUES(last_question_versions_json),"
            "seen_question_versions_json=VALUES(seen_question_versions_json),due_at=VALUES(due_at),"
            "last_settled_at=VALUES(last_settled_at),last_quiz_id=VALUES(last_quiz_id),"
            "last_event_id=VALUES(last_event_id),rule_version=VALUES(rule_version),updated_at=UTC_TIMESTAMP(6)",
            (owner, course_id, lesson_id, event["content_version"], schedule_seq, decision.stage,
             activity_date, dump(outcome.question_versions), dump(seen), _sql_time(decision.due_at),
             event["settled_at"], event["quiz_id"], event["event_id"], event["rule_version"]),
            conn=conn,
        )
        await execute(
            "UPDATE learning_course_reviews SET status='superseded',is_current=NULL,revision=revision+1,"
            "updated_at=UTC_TIMESTAMP(6) WHERE owner_id=%s AND lesson_id=%s AND content_version=%s AND is_current=1",
            (owner, lesson_id, event["content_version"]), conn=conn,
        )
        await execute(
            "INSERT INTO learning_course_reviews "
            "(review_id,owner_id,course_id,lesson_id,content_version,schedule_seq,due_at,timezone,rule_version,reason) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (uid("crv"), owner, course_id, lesson_id, event["content_version"], schedule_seq,
             _sql_time(decision.due_at), event["timezone"], event["rule_version"], decision.reason),
            conn=conn,
        )
        await _finish_event(conn, event)
        return 1


async def reconcile_course_reviews(limit=100):
    """Backfill one bounded page, then consume one page; failures stay pending."""
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")
    historical = await fetch_all(
        "SELECT link.owner_id,quiz.quiz_id FROM learning_course_quiz_links link "
        "JOIN quiz_tasks task ON task.task_id=link.task_id AND task.user_id=link.owner_id "
        "AND task.kind='quiz' AND task.mode='production' AND task.status='completed' "
        "JOIN quiz_sessions quiz ON quiz.quiz_id=task.quiz_id AND quiz.user_id=link.owner_id "
        "AND quiz.origin_task_id=task.task_id AND quiz.status='settled' AND quiz.settled_at IS NOT NULL "
        "LEFT JOIN learning_course_review_events event ON event.owner_id=link.owner_id AND event.quiz_id=quiz.quiz_id "
        "WHERE event.event_id IS NULL ORDER BY quiz.settled_at,quiz.quiz_id LIMIT %s",
        (limit,),
    )
    if historical:
        async with transaction() as conn:
            for row in historical:
                await append_settlement_event(conn, row["owner_id"], row["quiz_id"])
    pending = await fetch_all(
        "SELECT event_id,owner_id,course_id,lesson_id FROM learning_course_review_events "
        "WHERE processed_at IS NULL ORDER BY settled_at,quiz_id LIMIT %s",
        (limit,),
    )
    processed = 0
    for event in pending:
        processed += await _consume_event(event)
    return processed


async def purge_course_reviews(conn, owner, course_id):
    """Withdraw source-revoked entries while retaining immutable settlement IDs."""
    _require_transaction(conn)
    await execute(
        "UPDATE learning_course_reviews SET status='source_revoked',is_current=NULL,revision=revision+1,"
        "updated_at=UTC_TIMESTAMP(6) WHERE owner_id=%s AND course_id=%s AND status<>'source_revoked'",
        (owner, course_id), conn=conn,
    )
    await execute(
        "UPDATE learning_course_review_states SET due_at=NULL,updated_at=UTC_TIMESTAMP(6) "
        "WHERE owner_id=%s AND course_id=%s",
        (owner, course_id), conn=conn,
    )
    await execute(
        "UPDATE learning_course_review_events SET processed_at=UTC_TIMESTAMP(6),skipped_reason='source_revoked' "
        "WHERE owner_id=%s AND course_id=%s AND processed_at IS NULL",
        (owner, course_id), conn=conn,
    )


async def _review_rows(owner, course_id, *, conn=None):
    return await fetch_all(
        "SELECT review.*,task.status AS task_status,quiz.quiz_id,quiz.status AS quiz_status,quiz.settled_at "
        "FROM learning_course_reviews review "
        "JOIN learning_course_lessons lesson ON lesson.lesson_id=review.lesson_id AND lesson.course_id=review.course_id "
        "AND lesson.owner_id=review.owner_id AND lesson.content_version=review.content_version "
        "LEFT JOIN learning_course_quiz_links link ON link.link_id=review.active_link_id AND link.owner_id=review.owner_id "
        "AND link.course_id=review.course_id AND link.lesson_id=review.lesson_id AND link.content_version=review.content_version "
        "LEFT JOIN quiz_tasks task ON task.task_id=link.task_id AND task.user_id=link.owner_id "
        "AND task.kind='quiz' AND task.mode='production' "
        "LEFT JOIN quiz_sessions quiz ON quiz.quiz_id=task.quiz_id AND quiz.user_id=review.owner_id "
        "AND quiz.origin_task_id=task.task_id AND task.status='completed' "
        "WHERE review.owner_id=%s AND review.course_id=%s AND lesson.status='ready' "
        "AND lesson.content_json IS NOT NULL AND review.status<>'source_revoked' "
        "ORDER BY review.due_at,review.lesson_id,review.schedule_seq",
        (owner, course_id), conn=conn,
    )


def _review_view(row):
    status = row["status"]
    if status not in _TERMINAL and row["active_link_id"]:
        if row.get("quiz_status") == "settled" and row.get("settled_at"):
            status = "completed"
        elif row.get("task_status") in {"failed", "cancelled"}:
            status = "failed"
        elif row.get("task_status") == "completed" and row.get("quiz_id"):
            status = "ready"
        else:
            status = "generating"
    reasons = {
        "scheduled": "本课检查已结算，建议次日再做三题巩固。",
        "generating": "正在准备本轮复习的三题检查。",
        "ready": "题目已准备，完成作答并结算后会安排下次复习。",
        "failed": "上次复习出题未完成，可重新准备三题。",
        "completed": "本轮复习已结算，下次复习建议以最新结算为准。",
        "superseded": "已有更新的练习结算，请查看最新复习建议。",
        "source_revoked": "关联资料已失效。",
    }
    if status == "scheduled" and row["reason"] == "confirmed_wrong_or_partial":
        reasons["scheduled"] = "本次检查仍有待巩固内容，建议次日再做三题复习。"
    return CourseReviewView(
        review_id=row["review_id"], course_id=row["course_id"], lesson_id=row["lesson_id"],
        content_version=row["content_version"], schedule_seq=row["schedule_seq"],
        due_at=iso(_sql_time(_aware(row["due_at"]))), timezone=row["timezone"],
        status=status, revision=row["revision"], active_link_id=row["active_link_id"], reason=reasons[status],
    ).model_dump(mode="json")


async def list_course_reviews(owner, course_id):
    async with transaction() as conn:
        course = await course_read.owned_course(owner, course_id, conn=conn)
        await course_read.authorize_course(course, conn=conn)
        if course["status"] not in {"ready", "partial"}:
            return []
        rows = await _review_rows(owner, course_id, conn=conn)
        await course_read.authorize_course(course, conn=conn)
        return [_review_view(row) for row in rows]


async def _owned_review(owner, course_id, lesson_id, review_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM learning_course_reviews WHERE review_id=%s AND owner_id=%s AND course_id=%s AND lesson_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (review_id, owner, course_id, lesson_id), conn=conn,
    )
    if row is None:
        raise not_found()
    return row


def _unfinished(link):
    return link["task_status"] in {"pending", "running"} or (
        link["task_status"] == "completed" and not (
            link.get("quiz_id") and link["quiz_status"] == "settled" and link["settled_at"]
        )
    )


def _bound_reusable(review, links):
    if review["is_current"] != 1 or review["status"] in _TERMINAL:
        return None
    return next((link for link in links if (
        link["link_id"] == review["active_link_id"] and link["kind"] == "scheduled_review"
        and link["content_version"] == review["content_version"] and _unfinished(link)
    )), None)


def _start_checks(review, lesson, body, current_time):
    quizzes._check_lesson(lesson, body)
    if review["content_version"] != body.expected_content_version:
        raise conflict("revision_conflict", "复习对应的课文版本已变化")
    if review["is_current"] != 1 or review["status"] in _TERMINAL:
        raise conflict("course_review_changed", "这次复习已完成或被替代，请刷新课程")
    if review["revision"] != body.expected_revision:
        raise conflict("revision_conflict", "复习状态已变化，请刷新后重试")
    if not body.early and _aware(review["due_at"]) > current_time:
        raise conflict("course_review_not_due", "还未到建议复习时间，可明确选择提前复习")


async def _check_pending_settlement(conn, owner, lesson_id, version):
    pending = await fetch_one(
        "SELECT event_id FROM learning_course_review_events WHERE owner_id=%s AND lesson_id=%s "
        "AND content_version=%s AND processed_at IS NULL LIMIT 1",
        (owner, lesson_id, version), conn=conn,
    )
    if pending:
        raise conflict("course_review_changed", "正在根据最新结算更新复习建议，请稍后刷新")


async def start_course_review(actor, course_id, lesson_id, body: CourseReviewStart, key):
    body = CourseReviewStart.model_validate(body)
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise AppError(422, "idempotency_required", "需要有效 Idempotency-Key")
    owner = actor.owner_id
    course = await course_read.owned_course(owner, course_id)
    lesson = await course_read.owned_lesson(owner, course_id, lesson_id)
    scope = await course_read.authorize_course(course)
    quizzes._check_course(course)
    quizzes._check_lesson(lesson, body)
    review = await _owned_review(owner, course_id, lesson_id, body.review_id)
    request_hash = digest(dump({
        "operation": "course.lesson.scheduled_review", "course_id": course_id,
        "lesson_id": lesson_id, "body": body.model_dump(mode="json"),
    }))
    old = await job_service.existing_job(owner, "quiz", key, request_hash)
    links = await quizzes._link_rows(owner, course_id, lesson_id)
    if old:
        saved = next((link for link in links if link["task_id"] == old["task_id"]), None)
        if saved is None or saved["kind"] != "scheduled_review":
            raise conflict("course_quiz_link_missing", "复习任务缺少本课关联")
        return quizzes._link_view(saved)
    if review["content_version"] != body.expected_content_version:
        raise conflict("revision_conflict", "复习对应的课文版本已变化")
    reusable = _bound_reusable(review, links)
    if reusable:
        return quizzes._link_view(reusable)
    _start_checks(review, lesson, body, datetime.now(UTC))
    _, scope, request = quiz_service.resolved_quiz_request(actor, quizzes._scheduled_spec(course, lesson), scope)
    try:
        async with transaction() as conn:
            # Task first, then course/lesson/review, matching publication order.
            await job_service.enqueue_job(
                owner, "quiz", request, key, scope=scope.model_dump(mode="json"),
                request_hash=request_hash, conn=conn,
            )
            job = await job_service.existing_job(owner, "quiz", key, request_hash, conn=conn, lock=True)
            current_course = await course_read.owned_course(owner, course_id, conn=conn, lock=True)
            current_lesson = await course_read.owned_lesson(owner, course_id, lesson_id, conn=conn, lock=True)
            current_scope = await course_read.authorize_course(current_course, conn=conn)
            quizzes._check_course(current_course)
            quizzes._check_lesson(current_lesson, body)
            current = await _owned_review(owner, course_id, lesson_id, body.review_id, conn=conn, lock=True)
            links = await quizzes._link_rows(owner, course_id, lesson_id, conn=conn, lock=True)
            saved = next((link for link in links if link["task_id"] == job["task_id"]), None)
            if saved:
                return quizzes._link_view(saved)
            reusable = _bound_reusable(current, links)
            if reusable:
                raise quizzes._ReuseLink(reusable["link_id"])
            _start_checks(current, current_lesson, body, datetime.now(UTC))
            await _check_pending_settlement(conn, owner, lesson_id, body.expected_content_version)
            if any(_unfinished(link) for link in links if link["content_version"] == body.expected_content_version):
                raise conflict("course_quiz_in_progress", "本课还有未完成的检查，请先完成后再开始复习")
            _, current_scope, current_request = quiz_service.resolved_quiz_request(
                actor, quizzes._scheduled_spec(current_course, current_lesson), current_scope,
            )
            if job["request"] != current_request or ResolvedScope.model_validate(job["scope"]) != current_scope:
                raise conflict("revision_conflict", "课时复习范围已变化，请刷新后重试")
            link_id = uid("cql")
            await execute(
                "INSERT INTO learning_course_quiz_links "
                "(link_id,course_id,lesson_id,owner_id,task_id,kind,parent_link_id,content_version) "
                "VALUES(%s,%s,%s,%s,%s,'scheduled_review',NULL,%s)",
                (link_id, course_id, lesson_id, owner, job["task_id"], body.expected_content_version), conn=conn,
            )
            await execute(
                "UPDATE learning_course_reviews SET active_link_id=%s,status='generating',revision=revision+1,"
                "updated_at=UTC_TIMESTAMP(6) WHERE review_id=%s AND owner_id=%s",
                (link_id, body.review_id, owner), conn=conn,
            )
            links = await quizzes._link_rows(owner, course_id, lesson_id, conn=conn)
            return quizzes._link_view(next(link for link in links if link["link_id"] == link_id))
    except quizzes._ReuseLink as replay:
        links = await quizzes.list_quiz_links(owner, course_id, lesson_id)
        return next(link for link in links if link["link_id"] == replay.link_id)
