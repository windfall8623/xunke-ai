"""Effective learning-day streaks with rest days (C02).

有效学习日只来自服务器已保存的活动（B07 的同一事实适配器）；
打开页面、标记已读、任务生成成功都不计入。休息日只跳过不补签。
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter, ValidationError

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict
from app.core.values import dump, load, now, uid
from app.learning.contracts import IanaTimezone
from app.models.learning_habit import (
    HabitDay,
    HabitMilestone,
    HabitRestPreferences,
    HabitRestPreferencesUpdate,
    LearningHabitView,
)

MILESTONES = (1, 3, 7, 14, 30)
_WINDOW_DAYS = 28


def habit_activity_key(fact, local_date):
    if fact.kind == "self_check_saved":
        return (
            "self-check", fact.course_id, fact.lesson_id,
            fact.content_version, fact.check_ref, local_date,
        )
    return ("origin", fact.fact_id)


def effective_day(facts):
    return any(fact.kind in {
        "self_check_saved", "quiz_settled",
        "practice_completed", "course_application_submitted",
    } for fact in facts)


def calculate_streak(active_dates, rest_dates, today):
    """真实活动日 +1；事先生效的休息日跳过并单独计数；空白日停止。"""
    day = today if today in active_dates or today in rest_dates else today - timedelta(days=1)
    active_count, rest_count, pending_rest = 0, 0, 0
    oldest = min(active_dates | rest_dates, default=today)
    while day >= oldest:
        if day in active_dates:
            active_count += 1
            rest_count += pending_rest
            pending_rest = 0
        elif day in rest_dates:
            pending_rest += 1
        else:
            break
        day -= timedelta(days=1)
    return active_count, rest_count


async def get_rest_preferences(owner: int) -> HabitRestPreferences:
    row = await fetch_one(
        "SELECT * FROM learning_habit_rest_preferences WHERE owner_id=%s", (owner,)
    )
    if row is None:
        return HabitRestPreferences(weekly_rest_days=[], effective_from=date.today())
    return HabitRestPreferences(
        revision=row["revision"],
        weekly_rest_days=load(row["weekly_rest_days"], []),
        effective_from=row["effective_from"],
    )


async def update_rest_preferences(owner: int, body: HabitRestPreferencesUpdate):
    effective_from = body.effective_from or date.today()
    if effective_from < date.today():
        raise AppError(422, "invalid_effective_from", "休息计划只能从今天或未来生效，不能补签过去")
    async with transaction() as conn:
        row = await fetch_one(
            "SELECT * FROM learning_habit_rest_preferences WHERE owner_id=%s FOR UPDATE",
            (owner,), conn=conn,
        )
        if row is None:
            if body.expected_revision != 1:
                raise conflict("revision_conflict", "休息设置已更新，请刷新后重试")
            revision = 2
            await execute(
                "INSERT INTO learning_habit_rest_preferences(owner_id,weekly_rest_days,"
                "effective_from,revision) VALUES(%s,%s,%s,2)",
                (owner, dump(body.weekly_rest_days), effective_from), conn=conn,
            )
        else:
            if row["revision"] != body.expected_revision:
                raise conflict("revision_conflict", "休息设置已更新，请刷新后重试")
            revision = row["revision"] + 1
            await execute(
                "UPDATE learning_habit_rest_preferences SET weekly_rest_days=%s,"
                "effective_from=%s,revision=revision+1 WHERE owner_id=%s",
                (dump(body.weekly_rest_days), effective_from, owner), conn=conn,
            )
    return HabitRestPreferences(
        revision=revision, weekly_rest_days=body.weekly_rest_days,
        effective_from=effective_from,
    )


def _rest_dates(prefs: HabitRestPreferences, horizon: list[date], today: date) -> set[date]:
    if not prefs.weekly_rest_days or prefs.effective_from > today:
        return set()
    return {day for day in horizon if day.weekday() in set(prefs.weekly_rest_days)}


async def get_learning_habits(owner: int, timezone: IanaTimezone = "Asia/Shanghai", now_utc=None):
    from app.services import learning_summary_service

    try:
        timezone = TypeAdapter(IanaTimezone).validate_python(timezone)
    except (ValidationError, ValueError) as exc:
        raise AppError(422, "invalid_timezone", "请提供有效的 IANA 时区") from exc
    now_utc = now_utc or datetime.now(UTC)
    today_local = now_utc.astimezone(ZoneInfo(str(timezone))).date()
    prefs = await get_rest_preferences(owner)
    start_local = today_local - timedelta(days=_WINDOW_DAYS - 1)
    start_utc = datetime.combine(start_local, datetime.min.time(), tzinfo=ZoneInfo(str(timezone))).astimezone(UTC)
    facts = await learning_summary_service.load_activity_facts(owner, start_utc, now_utc)

    horizon = [start_local + timedelta(days=offset) for offset in range(_WINDOW_DAYS)]
    counts: dict[date, int] = {day: 0 for day in horizon}
    seen: set[tuple] = set()
    for fact in facts:
        local_date = datetime.fromisoformat(fact.occurred_at).astimezone(ZoneInfo(str(timezone))).date()
        if local_date not in counts:
            continue
        key = habit_activity_key(fact, local_date)
        if key in seen:
            continue
        seen.add(key)
        counts[local_date] += 1
    rest_dates = _rest_dates(prefs, horizon, today_local)
    active_dates = {day for day in horizon if counts[day] > 0}
    streak, rest_in_streak = calculate_streak(active_dates, rest_dates, today_local)
    recent = [
        HabitDay(
            local_date=day,
            kind="learning" if day in active_dates
            else ("rest" if day in rest_dates and day <= today_local
                  else ("today_pending" if day == today_local else "empty")),
            activity_count=counts[day],
        )
        for day in horizon
    ]
    all_active = set(active_dates)
    total = len(all_active)
    milestones = []
    for threshold in MILESTONES:
        ordered = sorted(all_active)
        reached_on = ordered[threshold - 1] if total >= threshold else None
        milestones.append(HabitMilestone(
            effective_days=threshold, reached=reached_on is not None, reached_on=reached_on,
        ))
    return LearningHabitView(
        local_date=today_local,
        timezone=timezone,
        effective_streak_days=streak,
        rest_days_in_streak=rest_in_streak,
        effective_days_total=total,
        last_effective_local_date=max(active_dates) if active_dates else None,
        recent_days=recent,
        milestones=milestones,
    )
