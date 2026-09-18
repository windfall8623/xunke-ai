"""Read-only weekly learning summary (B07).

事实只从既有学习表读取：同一 Quiz 的课程/空间/复习链接合并为一个 origin；
读取不创建学习事实、不回填队列、不启动任何模型任务。
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter, ValidationError

from app.core.db import fetch_all
from app.core.errors import AppError
from app.core.values import iso
from app.learning.contracts import IanaTimezone
from app.models.course_feedback import CourseCorrectionView
from app.models.learning_summary import (
    LearningActivityFact,
    WeeklyLearningCounts,
    WeeklyLearningSummary,
)

def quiz_fact_id(quiz_id: str) -> str:
    return "quiz-settled:" + quiz_id


def unique_activity_facts(facts):
    """同一活动的多来源行合并为一条；冲突的课程身份直接失败。"""
    by_id = {}
    for fact in sorted(facts, key=lambda item: (item.occurred_at, item.fact_id)):
        previous = by_id.get(fact.fact_id)
        if previous is None:
            by_id[fact.fact_id] = fact
            continue
        updates = {"is_scheduled_review": previous.is_scheduled_review or fact.is_scheduled_review}
        for field in ("course_id", "lesson_id", "content_version", "check_ref"):
            old_value, new_value = getattr(previous, field), getattr(fact, field)
            if old_value is not None and new_value is not None and old_value != new_value:
                raise ValueError("One activity has conflicting course identities")
            updates[field] = old_value if old_value is not None else new_value
        by_id[fact.fact_id] = previous.model_copy(update=updates)
    return list(by_id.values())


def week_bounds(week_start: date, timezone: IanaTimezone) -> tuple[datetime, datetime]:
    """本地周一 00:00 → 下周一 00:00，返回 UTC 区间。"""
    zone = ZoneInfo(str(timezone))
    start_local = datetime.combine(week_start, datetime.min.time(), tzinfo=zone)
    if start_local.weekday() != 0:
        raise AppError(422, "invalid_week_start", "week_start 必须是本周一的日期")
    end_local = start_local + timedelta(days=7)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


async def load_activity_facts(owner: int, start_utc: datetime, end_utc: datetime) -> list[LearningActivityFact]:
    facts: list[LearningActivityFact] = []
    for row in await fetch_all(
        "SELECT attempt_id,owner_id,course_id,lesson_id,content_version,check_ref,saved_at "
        "FROM learning_course_check_attempts WHERE owner_id=%s AND saved_at>=%s AND saved_at<%s "
        "AND revoked_at IS NULL",
        (owner, start_utc, end_utc),
    ):
        facts.append(LearningActivityFact(
            fact_id=f"self-check:{row['attempt_id']}", kind="self_check_saved",
            occurred_at=iso(row["saved_at"]), course_id=row["course_id"],
            lesson_id=row["lesson_id"], content_version=row["content_version"],
            origin_id=row["attempt_id"], check_ref=row["check_ref"],
        ))
    for row in await fetch_all(
        "SELECT quiz.quiz_id AS quiz_id,quiz.user_id,quiz.settled_at,link.course_id,"
        "link.lesson_id,link.content_version,link.kind FROM quiz_sessions quiz "
        "LEFT JOIN quiz_tasks task ON task.task_id=quiz.origin_task_id AND task.user_id=quiz.user_id "
        "LEFT JOIN learning_course_quiz_links link ON link.task_id=task.task_id "
        "AND link.owner_id=task.user_id "
        "WHERE quiz.user_id=%s AND quiz.settled_at IS NOT NULL "
        "AND quiz.settled_at>=%s AND quiz.settled_at<%s",
        (owner, start_utc, end_utc),
    ):
        scheduled = bool(row["kind"] in {"scheduled_review", "review"})
        facts.append(LearningActivityFact(
            fact_id=quiz_fact_id(row["quiz_id"]), kind="quiz_settled",
            occurred_at=iso(row["settled_at"]), course_id=row["course_id"],
            lesson_id=row["lesson_id"], content_version=row["content_version"],
            origin_id=row["quiz_id"], is_scheduled_review=scheduled,
        ))
    for row in await fetch_all(
        "SELECT practice_id,owner_id,completed_at FROM practice_sessions "
        "WHERE owner_id=%s AND completed_at IS NOT NULL "
        "AND completed_at>=%s AND completed_at<%s",
        (owner, start_utc, end_utc),
    ):
        facts.append(LearningActivityFact(
            fact_id=f"practice:{row['practice_id']}", kind="practice_completed",
            occurred_at=iso(row["completed_at"]), origin_id=row["practice_id"],
        ))
    for row in await fetch_all(
        "SELECT attempt_id,owner_id,course_id,saved_at,revoked_at FROM "
        "learning_course_application_attempts WHERE owner_id=%s AND saved_at>=%s "
        "AND saved_at<%s AND revoked_at IS NULL",
        (owner, start_utc, end_utc),
    ):
        facts.append(LearningActivityFact(
            fact_id=f"application:{row['attempt_id']}", kind="course_application_submitted",
            occurred_at=iso(row["saved_at"]), course_id=row["course_id"],
            origin_id=row["attempt_id"],
        ))
    return unique_activity_facts(facts)


async def weekly_summary(owner: int, week_start: date, timezone: IanaTimezone) -> WeeklyLearningSummary:
    try:
        timezone = TypeAdapter(IanaTimezone).validate_python(timezone)
    except (ValidationError, ValueError) as exc:
        raise AppError(422, "invalid_timezone", "请提供有效的 IANA 时区") from exc
    start_utc, end_utc = week_bounds(week_start, timezone)
    facts = await load_activity_facts(owner, start_utc, end_utc)
    counts = WeeklyLearningCounts(
        self_checks_saved=sum(f.kind == "self_check_saved" for f in facts),
        quizzes_settled=sum(f.kind == "quiz_settled" and not f.is_scheduled_review for f in facts),
        practices_completed=sum(f.kind == "practice_completed" for f in facts),
        applications_submitted=sum(f.kind == "course_application_submitted" for f in facts),
        scheduled_reviews_completed=sum(
            f.kind == "quiz_settled" and f.is_scheduled_review for f in facts),
    )

    course_ids = sorted({f.course_id for f in facts if f.course_id})
    course_outcomes = []
    warnings: list[str] = []
    if course_ids:
        from app.services import course_outcome_service, course_read

        for course_id in course_ids[:10]:
            try:
                course = await course_read.owned_course(owner, course_id)
                await course_read.authorize_course(course)
            except AppError:
                continue
            try:
                course_outcomes.append(await course_outcome_service.get_course_outcomes(owner, course_id))
            except AppError:
                warnings.append("部分课程的目标结果暂未读回，稍后刷新可重试。")

    confirmed_corrections = [
        CourseCorrectionView(
            correction_id=row["correction_id"], feedback_id=row["feedback_id"],
            supersedes_correction_id=row["supersedes_correction_id"], text=row["body"],
            source_refs=[], provenance=row["provenance"], confirmation=row["confirmation"],
            created_at=row["created_at"].isoformat(),
        )
        for row in await fetch_all(
            "SELECT c.* FROM learning_course_corrections c JOIN learning_course_feedback f "
            "ON f.feedback_id=c.feedback_id AND f.owner_id=c.owner_id "
            "WHERE c.owner_id=%s AND c.confirmation='confirmed' AND c.created_at>=%s "
            "AND c.created_at<%s ORDER BY c.created_at LIMIT 20",
            (owner, start_utc, end_utc),
        )
    ]

    from app.services import course_today_service

    today = await course_today_service.get_today(
        type("Actor", (), {"owner_id": owner})(), None, None,
    )
    next_actions = today["items"][:3]

    return WeeklyLearningSummary(
        week_start=week_start,
        week_end_exclusive=week_start + timedelta(days=7),
        timezone=timezone,
        counts=counts,
        course_outcomes=course_outcomes,
        confirmed_corrections=confirmed_corrections,
        next_actions=next_actions,
        warnings=warnings,
    )
