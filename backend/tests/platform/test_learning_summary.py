"""Weekly summary facts and reminder delivery boundaries (B07)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.db import execute, fetch_one
from app.core.values import dump, uid
from app.services.learning_notification_service import may_send_reminder
from app.services.learning_summary_service import (
    load_activity_facts,
    quiz_fact_id,
    unique_activity_facts,
    week_bounds,
)
from tests.platform.course_assessment_helpers import published_course


def test_quiz_fact_id_and_unique_activity_facts():
    assert quiz_fact_id("q1") == "quiz-settled:q1"
    from app.models.learning_summary import LearningActivityFact

    course_view = LearningActivityFact(
        fact_id="quiz-settled:q1", kind="quiz_settled", occurred_at="2026-09-10T00:00:00+00:00",
        course_id="c1", lesson_id="l1", content_version=1, origin_id="q1",
    )
    study_view = LearningActivityFact(
        fact_id="quiz-settled:q1", kind="quiz_settled", occurred_at="2026-09-10T00:00:01+00:00",
        origin_id="q1",
    )
    merged = unique_activity_facts([course_view, study_view])
    assert len(merged) == 1 and merged[0].course_id == "c1"
    assert merged[0].is_scheduled_review is False


def test_week_bounds_reject_non_monday_and_use_local_midnight():
    from datetime import date
    from zoneinfo import ZoneInfo

    start, end = week_bounds(date(2026, 9, 7), "Asia/Shanghai")  # 周一
    assert start.astimezone(ZoneInfo("Asia/Shanghai")).weekday() == 0
    assert (end - start).total_seconds() == 7 * 86400
    with pytest.raises(Exception):
        week_bounds(date(2026, 9, 9), "Asia/Shanghai")  # 周三


def test_may_send_reminder_matrix():
    assert may_send_reminder(enabled=False, paused_until=None, now_utc=2,
                             already_delivered=False, source_available=True) is False
    assert may_send_reminder(enabled=True, paused_until=None, now_utc=2,
                             already_delivered=True, source_available=True) is False
    assert may_send_reminder(enabled=True, paused_until=1, now_utc=2,
                             already_delivered=False, source_available=True) is True
    assert may_send_reminder(enabled=True, paused_until=None, now_utc=2,
                             already_delivered=False, source_available=False) is False


@pytest.mark.asyncio
async def test_weekly_summary_counts_each_fact_once(learner):
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(
        owner, [("cc1", "能解释返回值", "recognition", "返回值", "ready")])
    course_id = course["course_id"]
    lesson_id = course["goals"]["cc1"]["lesson_id"]
    now = datetime.now(UTC)
    await execute(
        "INSERT INTO learning_course_check_attempts(attempt_id,course_id,lesson_id,owner_id,"
        "content_version,check_ref,answer_json,idempotency_key,request_hash) "
        "VALUES(%s,%s,%s,%s,1,'check-1',%s,%s,%s)",
        (uid("att"), course_id, lesson_id, owner, dump({"answer": "理解"}),
         uid("k"), uid("h")),
    )

    start = now - timedelta(days=1)
    facts = await load_activity_facts(owner, start, now + timedelta(days=1))
    kinds = sorted(fact.kind for fact in facts)
    assert "self_check_saved" in kinds

    week_start = (now - timedelta(days=now.weekday())).date()
    summary = await api.get(
        f"/api/v1/study/weekly-summary?week_start={week_start.isoformat()}&timezone=Asia/Shanghai")
    assert summary.status_code == 200, summary.text
    data = summary.json()["data"]
    assert data["counts"]["self_checks_saved"] >= 1
    assert data["week_end_exclusive"] == (week_start + timedelta(days=7)).isoformat()


@pytest.mark.asyncio
async def test_reminder_preferences_default_off_and_outbox_dedup(learner):
    api, session = learner
    owner = session["user"]["id"]
    initial = await api.get("/api/v1/study/notification-preferences")
    assert initial.status_code == 200
    assert initial.json()["data"]["in_app_enabled"] is False
    assert initial.json()["data"]["email_enabled"] is False

    saved = await api.patch(
        "/api/v1/study/notification-preferences",
        json={"expected_revision": 1, "in_app_enabled": True, "email_enabled": False,
              "frequency": "weekly", "local_time": "09:00", "timezone": "Asia/Shanghai"},
    )
    assert saved.status_code == 200, saved.text

    due = datetime.now(UTC) - timedelta(hours=1)
    from app.services import learning_notification_service as reminders

    first = await reminders.enqueue_due_review_reminder(
        owner, lesson_title="返回值", link_path="/study", due_at=due)
    second = await reminders.enqueue_due_review_reminder(
        owner, lesson_title="返回值", link_path="/study", due_at=due)
    assert first and second is None  # 同身份重放不重复入队
    delivered = await reminders.deliver_due_reminders(apply=True)
    assert delivered >= 1
    reminders_list = await api.get("/api/v1/study/reminders")
    items = reminders_list.json()["data"]["items"]
    assert any(item["kind"] == "due_review" for item in items)
