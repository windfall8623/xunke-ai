"""Effective learning days: fact-based counting, rest without faking (C02)."""

from datetime import UTC, date, datetime, timedelta

import pytest

from app.core.values import dump, uid
from app.services.learning_habit_service import calculate_streak, habit_activity_key
from tests.platform.course_assessment_helpers import published_course


def test_rest_does_not_invent_learning_days():
    active = {date(2026, 9, 10), date(2026, 9, 12)}
    rest = {date(2026, 9, 11)}
    assert calculate_streak(active, rest, date(2026, 9, 12)) == (2, 1)
    assert calculate_streak(active, set(), date(2026, 9, 12)) == (1, 0)
    assert calculate_streak(active, rest, date(2026, 9, 13)) == (2, 1)
    # 计划算法：休息只在被后续学习日提交时计入；连续尚未建立时不累计。
    assert calculate_streak(set(), {date(2026, 9, 12)}, date(2026, 9, 12)) == (0, 0)


def test_activity_key_dedupes_self_checks_per_day():
    from app.models.learning_summary import LearningActivityFact

    fact = LearningActivityFact(
        fact_id="self-check:a1", kind="self_check_saved",
        occurred_at="2026-09-12T00:00:00+00:00", course_id="c1", lesson_id="l1",
        content_version=1, origin_id="a1", check_ref="check-1",
    )
    key = habit_activity_key(fact, date(2026, 9, 12))
    assert key == ("self-check", "c1", "l1", 1, "check-1", date(2026, 9, 12))


@pytest.mark.asyncio
async def test_habit_view_counts_saved_facts_only(learner):
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(
        owner, [("cc1", "能解释返回值", "recognition", "返回值", "ready")])
    course_id = course["course_id"]
    lesson_id = course["goals"]["cc1"]["lesson_id"]
    from app.core.db import execute

    await execute(
        "INSERT INTO learning_course_check_attempts(attempt_id,course_id,lesson_id,owner_id,"
        "content_version,check_ref,answer_json,idempotency_key,request_hash) "
        "VALUES(%s,%s,%s,%s,1,'check-1',%s,%s,%s)",
        (uid("att"), course_id, lesson_id, owner, dump({"answer": "今天保存的理解"}),
         uid("k"), uid("h")),
    )
    saved = await api.patch(
        "/api/v1/study/habit-preferences",
        json={"expected_revision": 1, "weekly_rest_days": [6]},
    )
    assert saved.status_code == 200, saved.text
    view = await api.get("/api/v1/study/habits")
    assert view.status_code == 200, view.text
    data = view.json()["data"]
    today = datetime.now(UTC).astimezone().date()
    assert data["effective_days_total"] >= 1
    assert data["milestones"][0]["effective_days"] == 1
    assert data["milestones"][0]["reached"] is True
    kinds = {day["local_date"]: day["kind"] for day in data["recent_days"]}
    assert kinds.get(today.isoformat(), data["recent_days"][-1]["kind"]) in {"learning", "today_pending"}
