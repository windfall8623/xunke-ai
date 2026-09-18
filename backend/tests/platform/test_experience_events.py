"""Diagnostics cannot leak content, cross owners, or become learning facts."""

import uuid

import pytest

from app.core.db import execute, fetch_one
from app.core.values import digest
from tests.platform.conftest import register_email_account
from tests.platform.test_course_preload import make_course, make_unit


@pytest.mark.asyncio
async def test_experience_receipt_is_idempotent_private_and_owner_scoped(learner):
    api, session = learner
    owner = session["user"]["id"]
    course, _, lessons = await make_course(owner, [make_unit("课时")])
    body = {"event_id": str(uuid.uuid4()), "name": "lesson_opened", "course_id": course, "lesson_id": lessons[0]}
    first = await api.post("/api/v1/experience/events", json=body)
    second = await api.post("/api/v1/experience/events", json=body)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert (await fetch_one("SELECT COUNT(*) AS n FROM learning_experience_events WHERE owner_id=%s", (owner,)))["n"] == 1
    assert (await api.post("/api/v1/experience/events", json={**body, "name": "learning_session_finished"})).status_code == 409
    # Raw answers, prompts and arbitrary properties cannot enter diagnostics.
    assert (await api.post("/api/v1/experience/events", json={**body, "answer": "private answer"})).status_code == 422
    progress = await fetch_one("SELECT read_at FROM learning_course_lessons WHERE lesson_id=%s", (lessons[0],))
    assert progress["read_at"] is None
    other, _ = await register_email_account(api)
    api.headers["X-CSRF-Token"] = other["csrf_token"]
    assert (await api.post("/api/v1/experience/events", json={**body, "event_id": str(uuid.uuid4())})).status_code == 404


@pytest.mark.asyncio
async def test_experience_sql_limit_retention_and_disable(learner, monkeypatch):
    from app.core.config import get_settings
    from app.services.experience_event_service import purge_experience_events

    api, session = learner
    owner = session["user"]["id"]
    for i in range(60):
        await execute(
            "INSERT INTO learning_experience_events(owner_id,event_id,name,body_hash) VALUES(%s,%s,'course_create_viewed',%s)",
            (owner, f"test-{i}", digest(str(i))),
        )
    body = {"event_id": str(uuid.uuid4()), "name": "course_create_viewed"}
    limited = await api.post("/api/v1/experience/events", json=body)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0
    await execute("UPDATE learning_experience_events SET received_at=UTC_TIMESTAMP(6)-INTERVAL 31 DAY WHERE owner_id=%s", (owner,))
    assert await purge_experience_events(owner_id=owner, dry_run=True) == 60
    assert await purge_experience_events(owner_id=owner) == 60
    monkeypatch.setattr(get_settings(), "experience_events_enabled", False)
    disabled = await api.post("/api/v1/experience/events", json=body)
    assert disabled.status_code == 202
    assert disabled.json()["data"]["accepted"] is False
    assert (await fetch_one("SELECT COUNT(*) AS n FROM learning_experience_events WHERE owner_id=%s", (owner,)))["n"] == 0
