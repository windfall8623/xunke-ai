import pytest

from tests.platform.test_learning import saved_quiz  # noqa: F401


@pytest.mark.asyncio
async def test_review_uses_original_approved_topic_and_keeps_private_weak_points_local(
    saved_quiz,
):
    from app.core.db import execute, fetch_one
    from app.core.values import dump, load

    api, _, quiz_id = saved_quiz
    row = await fetch_one(
        "SELECT questions_json FROM quiz_sessions WHERE quiz_id=%s", (quiz_id,)
    )
    questions = load(row["questions_json"])
    questions[0]["knowledge_point"] = "私有合成资料中的未公开配方"
    await execute(
        "UPDATE quiz_sessions SET user_input=%s,questions_json=%s WHERE quiz_id=%s",
        ("公开学习主题", dump(questions), quiz_id),
    )
    await api.put(
        f"/api/v1/quiz/{quiz_id}/answers/q1",
        json={"selected_answers": ["B"], "duration_ms": 100},
    )
    response = await api.post(
        "/api/v1/quiz/generate/async",
        json={"review_of_quiz_id": quiz_id, "question_count": 3},
        headers={"Idempotency-Key": "review-topic"},
    )
    assert response.status_code == 202, response.text
    task = await fetch_one(
        "SELECT request_json FROM quiz_tasks WHERE task_id=%s",
        (response.json()["data"]["task_id"],),
    )
    request = load(task["request_json"])
    assert request["user_input"] == "公开学习主题"
    assert request["objective_titles"] == ["私有合成资料中的未公开配方"]
    assert request["source_policy"] == "topic"


@pytest.mark.asyncio
async def test_review_of_unverified_legacy_quiz_requires_fresh_source_selection(
    saved_quiz,
):
    from app.core.db import execute

    api, _, quiz_id = saved_quiz
    await execute(
        "UPDATE quiz_sessions SET source_status='legacy_unverified',user_input='legacy topic' WHERE quiz_id=%s",
        (quiz_id,),
    )
    await api.put(
        f"/api/v1/quiz/{quiz_id}/answers/q1",
        json={"selected_answers": ["B"], "duration_ms": 100},
    )
    response = await api.post(
        "/api/v1/quiz/generate/async",
        json={"review_of_quiz_id": quiz_id, "question_count": 3},
        headers={"Idempotency-Key": "review-legacy"},
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "review_source_unverified"
