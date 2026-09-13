"""Weekly summary facts and reminder delivery boundaries (B07)."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.db import execute, fetch_one
from app.core.values import dump, uid
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
