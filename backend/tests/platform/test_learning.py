import asyncio

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def saved_quiz(learner):
    api, session = learner
    from app.core.db import execute
    from app.core.values import dump, uid

    quiz_id = uid("quiz")
    questions = [
        {
            "id": f"q{i}",
            "type": "single",
            "stem": f"第{i}题",
            "options": [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
            "answer": ["A"],
            "explanation": "独立测试事实",
            "knowledge_point": f"知识{i}",
            "difficulty": "easy",
            "citation_refs": [],
        }
        for i in range(1, 4)
    ]
    await execute(
        "INSERT INTO quiz_sessions(quiz_id,user_id,title,summary,questions_json,source_status) VALUES(%s,%s,%s,%s,%s,%s)",
        (
            quiz_id,
            session["user"]["id"],
            "测试题",
            "测试摘要",
            dump(questions),
            "model_only",
        ),
    )
    return api, session, quiz_id


@pytest.mark.asyncio
async def test_answer_truth_is_server_owned_and_replay_has_no_side_effects(saved_quiz):
    api, session, quiz_id = saved_quiz
    detail = await api.get(f"/api/v1/user/quizzes/{quiz_id}")
    assert detail.status_code == 200
    assert "answer" not in detail.json()["data"]["questions"][0]
    body = {"selected_answers": ["B"], "duration_ms": 200}
    first = await api.put(f"/api/v1/quiz/{quiz_id}/answers/q1", json=body)
    assert first.status_code == 200, first.text
    assert first.json()["data"]["answer_record"]["is_correct"] is False
    replay = await api.put(f"/api/v1/quiz/{quiz_id}/answers/q1", json=body)
    assert replay.json() == first.json()
    changed = await api.put(
        f"/api/v1/quiz/{quiz_id}/answers/q1",
        json={"selected_answers": ["A"], "duration_ms": 200},
    )
    assert changed.status_code == 409
    forged = await api.put(
        f"/api/v1/quiz/{quiz_id}/answers/q2",
        json={"selected_answers": ["X"], "duration_ms": 1},
    )
    assert forged.status_code == 422


@pytest.mark.asyncio
async def test_concurrent_completion_settles_once_and_reports_are_independent(
    saved_quiz,
):
    api, session, quiz_id = saved_quiz
    from app.core.db import fetch_one

    for i in range(1, 4):
        response = await api.put(
            f"/api/v1/quiz/{quiz_id}/answers/q{i}",
            json={"selected_answers": ["A"], "duration_ms": 100},
        )
        assert response.status_code == 200
    stale = await api.post(
        f"/api/v1/quiz/{quiz_id}/complete", json={"expected_revision": 1}
    )
    assert stale.status_code == 409
    outcomes = await asyncio.gather(
        *(
            api.post(f"/api/v1/quiz/{quiz_id}/complete", json={"expected_revision": 3})
            for _ in range(3)
        )
    )
    assert all(r.status_code == 200 for r in outcomes)
    assert all(r.json()["data"]["xp_awarded"] == 16 for r in outcomes)
    # Once settled, even a stale client returns the original receipt.
    replay = await api.post(
        f"/api/v1/quiz/{quiz_id}/complete", json={"expected_revision": 0}
    )
    assert replay.status_code == 200 and replay.json()["data"]["accuracy"] == 100
    row = await fetch_one(
        "SELECT total_xp FROM users WHERE id=%s", (session["user"]["id"],)
    )
    assert row["total_xp"] == 16
    row = await fetch_one(
        "SELECT COUNT(*) AS count FROM quiz_tasks WHERE quiz_id=%s AND kind='report'",
        (quiz_id,),
    )
    assert row["count"] == 1
    report = await api.get(f"/api/v1/report/{quiz_id}")
    assert (
        report.status_code == 200
        and report.json()["data"]["report_status"] == "pending"
    )


@pytest.mark.asyncio
async def test_foreign_quiz_and_task_return_404(saved_quiz):
    api, session, quiz_id = saved_quiz
    from app.core.db import execute

    await execute("UPDATE quiz_sessions SET user_id=NULL WHERE quiz_id=%s", (quiz_id,))
    assert (await api.get(f"/api/v1/user/quizzes/{quiz_id}")).status_code == 404
    assert (
        await api.put(
            f"/api/v1/quiz/{quiz_id}/answers/q1",
            json={"selected_answers": ["A"], "duration_ms": 1},
        )
    ).status_code == 404
