"""Reminder preferences, outbox identity and delivery boundaries (B07)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.learning_notification_service import (
    deliver_due_reminders,
    enqueue_due_review_reminder,
    may_send_reminder,
)


def test_may_send_reminder_matrix():
    assert may_send_reminder(enabled=False, paused_until=None, now_utc=2,
                             already_delivered=False, source_available=True) is False
    assert may_send_reminder(enabled=True, paused_until=None, now_utc=2,
                             already_delivered=True, source_available=True) is False
    assert may_send_reminder(enabled=True, paused_until=None, now_utc=2,
                             already_delivered=False, source_available=False) is False
    assert may_send_reminder(enabled=True, paused_until=1, now_utc=2,
                             already_delivered=False, source_available=True) is True


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
    first = await enqueue_due_review_reminder(
        owner, lesson_title="返回值", link_path="/study", due_at=due)
    second = await enqueue_due_review_reminder(
        owner, lesson_title="返回值", link_path="/study", due_at=due)
    assert first and second is None  # 同身份重放不重复入队
    delivered = await deliver_due_reminders(apply=True)
    assert delivered >= 1
    reminders_list = await api.get("/api/v1/study/reminders")
    items = reminders_list.json()["data"]["items"]
    assert any(item["kind"] == "due_review" for item in items)
