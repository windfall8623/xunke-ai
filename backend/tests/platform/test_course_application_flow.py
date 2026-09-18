"""A08 课程文本应用任务的 HTTP 全链路：先保存回答，再取反馈。

场景 V03/V05/V06 的应用部分：回答在排队反馈之前已持久化并能在反馈失败后读取；
模型反馈只写 provisional 且 independent_eligible=False，不能变成正式确认；
修改回答产生新 attempt 而不覆盖旧回答，supersedes 链按时间正确串联。
"""

import pytest
from app.core.db import execute, fetch_all, fetch_one
from app.core.values import load

from tests.platform.course_assessment_helpers import (  # noqa: F401 - course_worker fixture
    ScriptedApplicationGenerator, course_worker, feedback_proposal, published_course,
)

CRITERIA = [
    ("cc_explanation", "解释返回值如何被调用处使用", "explanation", "返回值的用法", "ready"),
    ("cc_gap", "在真实项目里排查参数错误", "application", "参数排查", "material_gap"),
]


def _worker(course_worker, application=None):
    return course_worker(application=application or ScriptedApplicationGenerator())


async def _assessment(api, course_worker, course, *, key="a08-check"):
    queued = await api.post(
        f"/api/v1/courses/{course['course_id']}/assessment-jobs",
        headers={"Idempotency-Key": key},
        json={"expected_course_revision": 2, "expected_criteria_revision": 1},
    )
    assert queued.status_code == 202, queued.text
    view = queued.json()["data"]
    runner, _ = _worker(course_worker)
    assert await runner.run_once(task_id=view["task_id"])
    return view["course_assessment_id"]


async def _applications(api, course_worker, course, assessment_id, *, key="a08-apply", application=None):
    queued = await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}/application-jobs",
        headers={"Idempotency-Key": key},
    )
    assert queued.status_code == 202, queued.text
    task_id = queued.json()["data"]["application_generation_task_id"]
    assert task_id
    runner, generator = _worker(course_worker, application)
    assert await runner.run_once(task_id=task_id)
    detail = await api.get(f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}")
    assert detail.status_code == 200, detail.text
    return detail.json()["data"], generator


async def _submit(api, course, assessment_id, application, *, key, answer, help_usage="unknown"):
    return await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}"
        f"/applications/{application['application_task_id']}/attempts",
        headers={"Idempotency-Key": key},
        json={"expected_revision": application["revision"], "answer": answer, "help_usage": help_usage},
    )


async def _feedback_job(api, course, assessment_id, attempt_id, *, key):
    return await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}"
        f"/attempts/{attempt_id}/feedback-jobs",
        headers={"Idempotency-Key": key},
    )


async def _attempt(api, course, assessment_id, attempt_id):
    result = await api.get(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}/attempts/{attempt_id}")
    assert result.status_code == 200, result.text
    return result.json()["data"]


@pytest.mark.asyncio
async def test_generated_application_hides_reference_answer_and_rubric(personal_learner, course_worker):
    """按需生成的应用任务只公开任务说明与验收维度，私有答案留在产物里。"""
    api, session = personal_learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    assessment_id = await _assessment(api, course_worker, course)
    before = await api.get(f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}")
    baseline = before.json()["data"]["covered_course_criterion_ids"]
    view, generator = await _applications(api, course_worker, course, assessment_id)
    assert generator.generated == 1 and len(view["applications"]) == 1
    application = view["applications"][0]
    assert application["source_policy"] == "topic"
    assert application["source_refs"] == [] and application["support_quotes"] == []
    assert application["course_criterion_ids"] == [
        course["goals"]["cc_explanation"]["course_criterion_id"]]
    assert application["latest_attempt_id"] is None
    public = str(view)
    for secret in ("私有参考答案", "reference_answer", "reference_point", "rubric", "weight"):
        assert secret not in public
    # 未作答的应用任务可见，但不改变已覆盖集合；资料缺口目标仍未覆盖。
    assert view["covered_course_criterion_ids"] == baseline
    assert view["uncovered_course_criterion_ids"] == [
        course["goals"]["cc_gap"]["course_criterion_id"]]

    row = await fetch_one("SELECT draft_json,evidence_json,question_version FROM "
                         "learning_course_application_tasks WHERE application_task_id=%s",
                         (application["application_task_id"],))
    private = load(row["draft_json"])
    assert private["rubric"]["reference_answer"].startswith("私有参考答案")
    assert load(row["evidence_json"]) == {}


@pytest.mark.asyncio
async def test_answer_survives_a_feedback_failure_and_can_be_retried(personal_learner, course_worker):
    """反馈调用失败不丢回答：答案先落库，重试反馈是显式操作。"""
    api, session = personal_learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    assessment_id = await _assessment(api, course_worker, course)
    view, _ = await _applications(api, course_worker, course, assessment_id)
    application = view["applications"][0]

    answer = "参数把调用处的数据带进函数，return 把结果交回调用处继续计算。"
    saved = await _submit(api, course, assessment_id, application, key="a08-answer", answer=answer)
    assert saved.status_code == 201, saved.text
    attempt = saved.json()["data"]
    assert attempt["answer"] == answer and attempt["feedback"] is None
    assert attempt["feedback_task_id"] and attempt["feedback_task"]["status"] == "pending"

    # 反馈任务本身失败：回答与其收据仍然完整可读。
    failing = ScriptedApplicationGenerator(feedback_error=TimeoutError("scripted provider timeout"))
    runner, generator = _worker(course_worker, failing)
    assert await runner.run_once(task_id=attempt["feedback_task_id"])
    assert generator.graded == 1
    task = await fetch_one("SELECT status FROM quiz_tasks WHERE task_id=%s", (attempt["feedback_task_id"],))
    assert task["status"] == "failed"
    stored = await _attempt(api, course, assessment_id, attempt["attempt_id"])
    assert stored["answer"] == answer
    # 终态调和为回答留下可见的未完成反馈，而不是伪造成绩。
    assert stored["feedback"]["status"] == "failed"
    assert stored["feedback"]["confirmation"] == "provisional"
    assert stored["feedback"]["score"] is None

    retried = await _feedback_job(api, course, assessment_id, attempt["attempt_id"], key="a08-retry")
    assert retried.status_code == 202, retried.text
    retry_task = retried.json()["data"]["feedback_task_id"]
    assert retry_task and retry_task != attempt["feedback_task_id"]
    runner, generator = _worker(course_worker)
    assert await runner.run_once(task_id=retry_task)
    final = await _attempt(api, course, assessment_id, attempt["attempt_id"])
    assert final["answer"] == answer and final["feedback"]["status"] == "graded"
    # 重试后的正式记录取代失败记录，但仍保持 provisional。
    assert final["feedback"]["confirmation"] == "provisional"
    assert final["feedback"]["supersedes_assessment_id"] == stored["feedback"]["assessment_id"]


@pytest.mark.asyncio
async def test_model_feedback_stays_provisional_and_never_verifies(personal_learner, course_worker):
    """模型反馈只是暂定评价：不能成为确认成绩，也不能让目标显示已验证。"""
    api, session = personal_learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    assessment_id = await _assessment(api, course_worker, course)
    view, _ = await _applications(api, course_worker, course, assessment_id)
    application = view["applications"][0]
    answer = "参数是输入，返回值交回调用处，调用处可以继续参与计算。"
    saved = await _submit(api, course, assessment_id, application, key="a08-provisional",
                          answer=answer, help_usage="none")
    assert saved.status_code == 201, saved.text
    attempt = saved.json()["data"]
    runner, _ = _worker(course_worker)
    assert await runner.run_once(task_id=attempt["feedback_task_id"])

    graded = await _attempt(api, course, assessment_id, attempt["attempt_id"])
    assert graded["feedback"]["status"] == "graded"
    assert graded["feedback"]["confirmation"] == "provisional"
    from decimal import Decimal

    assert Decimal(graded["feedback"]["score"]) == 1
    row = await fetch_one(
        "SELECT source,confirmation,independent_eligible,score FROM "
        "learning_course_application_assessments WHERE assessment_id=%s",
        (graded["feedback"]["assessment_id"],),
    )
    # 满分的模型反馈依然不是独立确认的证据。
    assert row["source"] == "model" and row["confirmation"] == "provisional"
    assert row["independent_eligible"] == 0 and row["score"] == 1

    summary = (await api.get(f"/api/v1/courses/{course['course_id']}/outcomes")).json()["data"]
    outcome = next(item for item in summary["criteria"]
                   if item["course_criterion_id"] == course["goals"]["cc_explanation"]["course_criterion_id"])
    assert outcome["status"] == "unverified"
    assert "暂定" in outcome["reason"] and outcome["evidence_refs"]


@pytest.mark.asyncio
async def test_uncertain_feedback_needs_review_without_a_score(personal_learner, course_worker):
    """不确定的反馈保持 needs_review 且没有分数，不进入正确率。"""
    api, session = personal_learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    assessment_id = await _assessment(api, course_worker, course)
    view, _ = await _applications(api, course_worker, course, assessment_id)
    application = view["applications"][0]
    answer = "返回值大概是函数算完之后的东西。"
    saved = await _submit(api, course, assessment_id, application, key="a08-uncertain", answer=answer)
    attempt = saved.json()["data"]
    uncertain = ScriptedApplicationGenerator(proposal=feedback_proposal(
        quotes=[answer[:6]], credits=("uncertain", "half"), status="needs_review",
        reasons=["回答未明确说明调用处如何使用返回值"]))
    runner, _ = _worker(course_worker, uncertain)
    assert await runner.run_once(task_id=attempt["feedback_task_id"])
    graded = await _attempt(api, course, assessment_id, attempt["attempt_id"])
    assert graded["feedback"]["status"] == "needs_review"
    assert graded["feedback"]["score"] is None
    assert graded["feedback"]["confirmation"] == "provisional"
    summary = (await api.get(f"/api/v1/courses/{course['course_id']}/outcomes")).json()["data"]
    outcome = next(item for item in summary["criteria"]
                   if item["course_criterion_id"] == course["goals"]["cc_explanation"]["course_criterion_id"])
    assert outcome["status"] == "unverified"


@pytest.mark.asyncio
async def test_new_attempt_inserts_and_chains_supersedes(personal_learner, course_worker):
    """修改回答形成新 attempt：旧回答与旧反馈都保留，新反馈按链串联。"""
    api, session = personal_learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    assessment_id = await _assessment(api, course_worker, course)
    view, _ = await _applications(api, course_worker, course, assessment_id)
    application = view["applications"][0]

    first_answer = "参数是输入，返回值是输出。"
    first = await _submit(api, course, assessment_id, application, key="a08-first", answer=first_answer)
    assert first.status_code == 201, first.text
    first_attempt = first.json()["data"]
    runner, _ = _worker(course_worker)
    assert await runner.run_once(task_id=first_attempt["feedback_task_id"])
    first_graded = await _attempt(api, course, assessment_id, first_attempt["attempt_id"])

    refreshed = await api.get(f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}")
    second_answer = "参数把调用处的数据带进函数，返回值交回调用处，可以继续参与后面的计算。"
    second = await _submit(api, course, assessment_id, refreshed.json()["data"]["applications"][0],
                           key="a08-second", answer=second_answer)
    assert second.status_code == 201, second.text
    second_attempt = second.json()["data"]
    assert second_attempt["attempt_id"] != first_attempt["attempt_id"]
    runner, _ = _worker(course_worker)
    assert await runner.run_once(task_id=second_attempt["feedback_task_id"])

    # 旧 attempt 与旧反馈仍可原样读取，没有被新回答覆盖。
    kept = await _attempt(api, course, assessment_id, first_attempt["attempt_id"])
    assert kept["answer"] == first_answer
    assert kept["feedback"]["assessment_id"] == first_graded["feedback"]["assessment_id"]
    latest = await _attempt(api, course, assessment_id, second_attempt["attempt_id"])
    assert latest["answer"] == second_answer

    answers = await fetch_all(
        "SELECT attempt_id,answer_text,latest_assessment_id FROM learning_course_application_attempts "
        "WHERE course_assessment_id=%s AND owner_id=%s ORDER BY saved_at,attempt_id", (assessment_id, owner))
    assert [row["answer_text"] for row in answers] == [first_answer, second_answer]
    # 每次 attempt 有自己的评分身份；supersedes 只在同一 attempt 内串联。
    grades = await fetch_all(
        "SELECT assessment_id,attempt_id,supersedes_assessment_id FROM "
        "learning_course_application_assessments WHERE owner_id=%s ORDER BY created_at,assessment_id", (owner,))
    assert len(grades) == 2
    assert {row["attempt_id"] for row in grades} == {first_attempt["attempt_id"], second_attempt["attempt_id"]}
    assert all(row["supersedes_assessment_id"] is None for row in grades)


@pytest.mark.asyncio
async def test_duplicate_submit_and_generation_keys_stay_idempotent(personal_learner, course_worker):
    """同键重复提交返回同一 attempt；同键再排应用题不新增任务。"""
    api, session = personal_learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    assessment_id = await _assessment(api, course_worker, course)
    view, generator = await _applications(api, course_worker, course, assessment_id, key="a08-gen")
    application = view["applications"][0]

    replay_generation = await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}/application-jobs",
        headers={"Idempotency-Key": "a08-gen"})
    assert replay_generation.status_code == 202, replay_generation.text
    assert replay_generation.json()["data"]["application_task_ids"] == view["application_task_ids"]
    # 另一个操作标识也不会在已有任务之上再生成一组。
    other_key = await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}/application-jobs",
        headers={"Idempotency-Key": "a08-gen-other"})
    assert other_key.status_code == 202, other_key.text
    assert other_key.json()["data"]["application_task_ids"] == view["application_task_ids"]
    assert len(await fetch_all(
        "SELECT task_id FROM quiz_tasks WHERE user_id=%s AND kind='course_application_generate'", (owner,))) == 1

    answer = "参数是输入；返回值交回调用处继续使用。"
    first = await _submit(api, course, assessment_id, application, key="a08-dup", answer=answer)
    assert first.status_code == 201, first.text
    replay = await _submit(api, course, assessment_id, application, key="a08-dup", answer=answer)
    assert replay.status_code == 201, replay.text
    assert replay.json()["data"]["attempt_id"] == first.json()["data"]["attempt_id"]
    conflict = await _submit(api, course, assessment_id, application, key="a08-dup", answer=answer + "补充。")
    assert conflict.status_code == 409 and conflict.json()["error_code"] == "idempotency_conflict"
    assert len(await fetch_all(
        "SELECT attempt_id FROM learning_course_application_attempts WHERE owner_id=%s", (owner,))) == 1
    assert len(await fetch_all(
        "SELECT task_id FROM quiz_tasks WHERE user_id=%s AND kind='course_application_feedback'", (owner,))) == 1


@pytest.mark.asyncio
async def test_answer_is_saved_before_the_feedback_queue_is_reachable(personal_learner, course_worker):
    """反馈排队不可用时提交仍成功：答案与幂等收据先于任何队列写入提交。"""
    api, session = personal_learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    assessment_id = await _assessment(api, course_worker, course)
    view, _ = await _applications(api, course_worker, course, assessment_id)
    application = view["applications"][0]

    from app.core.errors import AppError
    from app.services import course_application_service as applications

    async def unavailable(*args, **kwargs):
        raise AppError(503, "queue_unavailable", "scripted queue outage")

    original = applications.create_feedback_job
    applications.create_feedback_job = unavailable
    try:
        answer = "返回值交回调用处，之后可以参与别的计算。"
        saved = await _submit(api, course, assessment_id, application, key="a08-outage", answer=answer)
    finally:
        applications.create_feedback_job = original
    assert saved.status_code == 201, saved.text
    attempt = saved.json()["data"]
    assert attempt["answer"] == answer
    assert attempt["feedback_task_id"] is None and attempt["feedback"] is None
    assert not await fetch_all(
        "SELECT task_id FROM quiz_tasks WHERE user_id=%s AND kind='course_application_feedback'", (owner,))
    # 恢复后显式重试反馈即可，回答不需要重新输入。
    queued = await _feedback_job(api, course, assessment_id, attempt["attempt_id"], key="a08-recover")
    assert queued.status_code == 202, queued.text
    runner, _ = _worker(course_worker)
    assert await runner.run_once(task_id=queued.json()["data"]["feedback_task_id"])
    graded = await _attempt(api, course, assessment_id, attempt["attempt_id"])
    assert graded["answer"] == answer and graded["feedback"]["status"] == "graded"


@pytest.mark.asyncio
async def test_sealed_check_and_other_accounts_cannot_write_applications(personal_learner, course_worker):
    """封存后不再接收新回答；另一账号既读不到也写不了应用任务。"""
    from tests.platform.conftest import register_email_account

    api, session = personal_learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    assessment_id = await _assessment(api, course_worker, course)
    view, _ = await _applications(api, course_worker, course, assessment_id)
    application = view["applications"][0]
    answer = "参数带来输入，返回值交回调用处。"
    saved = await _submit(api, course, assessment_id, application, key="a08-seal", answer=answer)
    attempt = saved.json()["data"]
    runner, _ = _worker(course_worker)
    assert await runner.run_once(task_id=attempt["feedback_task_id"])

    quiz = await fetch_one(
        "SELECT quiz_id FROM learning_course_assessments WHERE course_assessment_id=%s", (assessment_id,))
    detail = await api.get(f"/api/v1/user/quizzes/{quiz['quiz_id']}")
    for question in detail.json()["data"]["questions"]:
        answered = await api.put(f"/api/v1/quiz/{quiz['quiz_id']}/answers/{question['id']}",
                                 json={"selected_answers": ["A"], "duration_ms": 120})
        assert answered.status_code == 200, answered.text
    settled = await api.post(f"/api/v1/quiz/{quiz['quiz_id']}/complete",
                             json={"expected_revision": len(detail.json()["data"]["questions"])})
    assert settled.status_code == 200, settled.text
    current = await api.get(f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}")
    sealed = await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}/complete",
        headers={"Idempotency-Key": "a08-seal-complete"},
        json={"expected_revision": current.json()["data"]["revision"], "help_usage": "none"})
    assert sealed.status_code == 200, sealed.text
    # 已提交的应用回答记录在封存快照里，但仍不是正式确认的目标证据。
    completion = load((await fetch_one(
        "SELECT completion_json FROM learning_course_assessments WHERE course_assessment_id=%s",
        (assessment_id,)))["completion_json"])
    assert completion["attempt_ids"] == [attempt["attempt_id"]]

    refreshed = await api.get(f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}")
    blocked = await _submit(api, course, assessment_id, refreshed.json()["data"]["applications"][0],
                            key="a08-after-seal", answer="封存之后的新回答。")
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "course_assessment_completed"

    other, _ = await register_email_account(api, nickname="其他学习者")
    api.headers.update({"X-CSRF-Token": other["csrf_token"], "Origin": "http://testserver"})
    assert (await api.get(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}/attempts/{attempt['attempt_id']}"
    )).status_code == 404
    assert (await _submit(api, course, assessment_id, application, key="a08-cross",
                          answer="越权写入尝试。")).status_code == 404
    assert (await _feedback_job(api, course, assessment_id, attempt["attempt_id"],
                                key="a08-cross-feedback")).status_code == 404


@pytest.mark.asyncio
async def test_revoked_course_hides_saved_answers_without_leaking_text(personal_learner, course_worker):
    """课程资料撤销后回答不可读，也不泄漏正文；反馈任务不再重排。"""
    api, session = personal_learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    assessment_id = await _assessment(api, course_worker, course)
    view, _ = await _applications(api, course_worker, course, assessment_id)
    application = view["applications"][0]
    answer = "只有本人可读的回答正文。"
    saved = await _submit(api, course, assessment_id, application, key="a08-revoke", answer=answer)
    attempt = saved.json()["data"]

    from app.core.db import transaction
    from app.services.course_assessment_service import purge_course_assessments

    async with transaction() as conn:
        await purge_course_assessments(conn, owner, course["course_id"])
    await execute("UPDATE learning_courses SET status='source_revoked',resolved_scope_json=NULL "
                  "WHERE course_id=%s AND owner_id=%s", (course["course_id"], owner))

    blocked = await api.get(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}/attempts/{attempt['attempt_id']}")
    assert blocked.status_code == 404 and blocked.json()["error_code"] == "source_revoked"
    assert answer not in blocked.text
    again = await _feedback_job(api, course, assessment_id, attempt["attempt_id"], key="a08-revoke-retry")
    assert again.status_code == 404 and again.json()["error_code"] == "source_revoked"
    stored = await fetch_one("SELECT answer_text,revoked_at FROM learning_course_application_attempts "
                             "WHERE attempt_id=%s", (attempt["attempt_id"],))
    assert stored["answer_text"] is None and stored["revoked_at"] is not None
