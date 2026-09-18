"""Unverifiable legacy events must not starve valid course review settlements."""

import pytest

from app.core.db import fetch_all, fetch_one
from app.services import course_review_service as reviews
from tests.platform.course_assessment_helpers import (  # noqa: F401 - course_worker fixture
    ScriptedQuizGenerator, course_worker,
)
from tests.platform.test_course_assessment_authorization import (
    _answer_all, _course, _ordinary_course_quiz,
)


@pytest.mark.asyncio
async def test_unverifiable_legacy_event_does_not_block_valid_review(learner, course_worker, monkeypatch):
    api, session = learner
    owner = session["user"]["id"]

    async def owner_queue(sql, args=(), *, conn=None):
        # Integration fixtures share SQL but use different artifact roots.
        # Scope queue discovery to this fixture; consume/validation stays real.
        if "WHERE event.event_id IS NULL ORDER BY" in sql:
            sql = sql.replace("WHERE event.event_id IS NULL", "WHERE event.event_id IS NULL AND link.owner_id=%s")
            args = (owner, *args)
        elif "WHERE processed_at IS NULL ORDER BY settled_at,quiz_id" in sql:
            sql = sql.replace("WHERE processed_at IS NULL", "WHERE owner_id=%s AND processed_at IS NULL")
            args = (owner, *args)
        return await fetch_all(sql, args, conn=conn)

    monkeypatch.setattr(reviews, "fetch_all", owner_queue)
    legacy_course, current_course = await _course(owner), await _course(owner)
    legacy_quiz = await _ordinary_course_quiz(owner, legacy_course)

    # A current quiz goes through the real publication path, so its generation
    # artifact, hash and question identities are all checked by reconciliation.
    queued = await api.post(
        f"/api/v1/courses/{current_course['course_id']}/lessons/{current_course['lesson_id']}/quiz-jobs",
        headers={"Idempotency-Key": "current-review-fixture"},
        json={"expected_content_version": 1},
    )
    assert queued.status_code == 202, queued.text
    task_id = queued.json()["data"]["task"]["task_id"]
    runner, _ = course_worker(ScriptedQuizGenerator(refs_for=lambda target: []))
    assert await runner.run_once(task_id=task_id)
    task = await fetch_one("SELECT status,quiz_id FROM quiz_tasks WHERE task_id=%s", (task_id,))
    assert task["status"] == "completed"
    current_quiz = task["quiz_id"]

    # This order reproduces the poison event at the front of the same queue.
    for quiz_id in (legacy_quiz, current_quiz):
        await _answer_all(api, quiz_id)
        settled = await api.post(f"/api/v1/quiz/{quiz_id}/complete", json={"expected_revision": 3})
        assert settled.status_code == 200, settled.text
    original_xp = (await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,)))["total_xp"]
    original_legacy = await fetch_one(
        "SELECT status,settled_at,xp_awarded,rag_run_id FROM quiz_sessions WHERE quiz_id=%s", (legacy_quiz,))
    assert original_legacy["rag_run_id"] is None

    assert await reviews.reconcile_course_reviews() == 2
    events = {row["quiz_id"]: row for row in await fetch_all(
        "SELECT quiz_id,processed_at,skipped_reason FROM learning_course_review_events WHERE owner_id=%s", (owner,))}
    assert events[legacy_quiz]["processed_at"] is not None
    assert events[legacy_quiz]["skipped_reason"] == "quiz_evidence_unavailable"
    assert events[current_quiz]["processed_at"] is not None
    assert events[current_quiz]["skipped_reason"] is None
    states = await fetch_all(
        "SELECT course_id,last_quiz_id,schedule_seq FROM learning_course_review_states WHERE owner_id=%s", (owner,))
    assert states == [{"course_id": current_course["course_id"], "last_quiz_id": current_quiz, "schedule_seq": 1}]
    assert len(await fetch_all("SELECT review_id FROM learning_course_reviews WHERE owner_id=%s", (owner,))) == 1
    assert await reviews.reconcile_course_reviews() == 0
    assert (await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,)))["total_xp"] == original_xp
    assert await fetch_one(
        "SELECT status,settled_at,xp_awarded,rag_run_id FROM quiz_sessions WHERE quiz_id=%s", (legacy_quiz,)) == original_legacy
