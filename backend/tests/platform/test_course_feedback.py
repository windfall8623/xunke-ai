"""Course feedback issues, corrections and authorized regrades (B03)."""

import pytest

from app.core.db import execute, fetch_one
from app.core.values import dump, uid
from app.services.course_feedback_service import correction_effect
from tests.platform.course_assessment_helpers import (  # noqa: F401 - course_worker fixture
    ScriptedApplicationGenerator, course_worker, published_course,
)


async def _save_check_attempt(owner, course_id, lesson_id, check_ref="check-1"):
    attempt_id = uid("att")
    await execute(
        "INSERT INTO learning_course_check_attempts(attempt_id,course_id,lesson_id,owner_id,"
        "content_version,check_ref,answer_json,idempotency_key,request_hash) "
        "VALUES(%s,%s,%s,%s,1,%s,%s,%s,%s)",
        (attempt_id, course_id, lesson_id, owner, check_ref, dump({"answer": "我的理解"}),
         uid("key"), uid("hash")),
    )
    return attempt_id


@pytest.mark.asyncio
async def test_lesson_feedback_replay_and_target_guards(learner):
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, [("cc1", "能解释局部变量", "recognition", "变量作用域", "ready")])
    course_id = course["course_id"]
    lesson_id = course["goals"]["cc1"]["lesson_id"]
    body = {"issue_kind": "confusion",
            "target": {"kind": "lesson", "lesson_id": lesson_id, "content_version": 1,
                       "block_index": 0},
            "comment": "这一段没有说明和外层变量的区别。"}
    created = await api.post(f"/api/v1/courses/{course_id}/feedback", json=body,
                             headers={"Idempotency-Key": "fb-1", "Origin": "http://testserver"})
    assert created.status_code == 201, created.text
    feedback_id = created.json()["data"]["feedback_id"]
    assert created.json()["data"]["target"]["kind"] == "lesson"

    replay = await api.post(f"/api/v1/courses/{course_id}/feedback", json=body,
                            headers={"Idempotency-Key": "fb-1", "Origin": "http://testserver"})
    assert replay.status_code == 201
    assert replay.json()["data"]["feedback_id"] == feedback_id

    other = {**body, "comment": "换一个不同的问题"}
    conflict = await api.post(f"/api/v1/courses/{course_id}/feedback", json=other,
                              headers={"Idempotency-Key": "fb-1", "Origin": "http://testserver"})
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "idempotency_conflict"

    stale = {**body, "target": {**body["target"], "content_version": 9}}
    old = await api.post(f"/api/v1/courses/{course_id}/feedback", json=stale,
                         headers={"Idempotency-Key": "fb-2", "Origin": "http://testserver"})
    assert old.status_code == 409

    outside = {**body, "target": {**body["target"], "block_index": 9}}
    oob = await api.post(f"/api/v1/courses/{course_id}/feedback", json=outside,
                         headers={"Idempotency-Key": "fb-3", "Origin": "http://testserver"})
    assert oob.status_code == 409

    listing = await api.get(f"/api/v1/courses/{course_id}/feedback?lesson_id={lesson_id}")
    assert listing.status_code == 200
    assert listing.json()["data"]["total"] == 1


@pytest.mark.asyncio
async def test_cross_user_course_feedback_is_not_found(learner):
    api, session = learner
    owner = session["user"]["id"]
    mine = await published_course(owner, [("cc1", "目标甲", "recognition", "第一课", "ready")])
    from tests.platform.conftest import register_email_account

    stranger_session, _ = await register_email_account(api)
    api.headers["X-CSRF-Token"] = stranger_session["csrf_token"]
    stranger_owner = stranger_session["user"]["id"]
    stranger = await published_course(stranger_owner,
                                      [("cc1", "目标乙", "recall", "第二课", "ready")])
    body = {"issue_kind": "content_error",
            "target": {"kind": "lesson", "lesson_id": mine["goals"]["cc1"]["lesson_id"],
                       "content_version": 1, "block_index": 0},
            "comment": "示例写错了。"}
    # 他人课程的课时定位必须 404，不能创建也不能串接。
    response = await api.post(f"/api/v1/courses/{mine['course_id']}/feedback", json=body,
                              headers={"Idempotency-Key": "fb-x", "Origin": "http://testserver"})
    assert response.status_code == 404, response.text
    foreign = await api.get(f"/api/v1/courses/{mine['course_id']}/feedback")
    assert foreign.status_code == 200
    assert foreign.json()["data"]["total"] == 0
    own = await api.get(f"/api/v1/courses/{stranger['course_id']}/feedback")
    assert own.json()["data"]["total"] == 0


@pytest.mark.asyncio
async def test_self_check_correction_flow(learner):
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, [("cc1", "能解释返回值", "recall", "返回值", "ready")])
    course_id = course["course_id"]
    lesson_id = course["goals"]["cc1"]["lesson_id"]
    attempt_id = await _save_check_attempt(owner, course_id, lesson_id)
    body = {"issue_kind": "confusion",
            "target": {"kind": "self_check", "lesson_id": lesson_id, "content_version": 1,
                       "check_attempt_id": attempt_id},
            "comment": "不确定这里的说法。"}
    created = await api.post(f"/api/v1/courses/{course_id}/feedback", json=body,
                             headers={"Idempotency-Key": "fb-c1", "Origin": "http://testserver"})
    assert created.status_code == 201, created.text
    feedback_id = created.json()["data"]["feedback_id"]

    correction = await api.post(
        f"/api/v1/courses/{course_id}/feedback/{feedback_id}/corrections",
        json={"expected_revision": 1, "text": "正确说法应是……"},
        headers={"Idempotency-Key": "cor-1", "Origin": "http://testserver"},
    )
    assert correction.status_code == 201, correction.text
    view = correction.json()["data"]
    assert view["provenance"] == "learner_note"
    assert view["confirmation"] == "provisional"

    replay = await api.post(
        f"/api/v1/courses/{course_id}/feedback/{feedback_id}/corrections",
        json={"expected_revision": 1, "text": "正确说法应是……"},
        headers={"Idempotency-Key": "cor-1", "Origin": "http://testserver"},
    )
    assert replay.status_code == 201
    assert replay.json()["data"]["correction_id"] == view["correction_id"]

    listing = await api.get(
        f"/api/v1/courses/{course_id}/feedback?check_attempt_id={attempt_id}"
    )
    data = listing.json()["data"]
    assert data["total"] == 1
    assert data["items"][0]["corrections"][0]["text"] == "正确说法应是……"


@pytest.mark.asyncio
async def test_review_flow_keeps_provenance_rules(learner):
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, [("cc1", "能解释作用域", "recognition", "作用域", "ready")])
    course_id = course["course_id"]
    lesson_id = course["goals"]["cc1"]["lesson_id"]
    body = {"issue_kind": "content_error",
            "target": {"kind": "lesson", "lesson_id": lesson_id, "content_version": 1,
                       "block_index": 0},
            "comment": "正文与资料矛盾。"}
    created = await api.post(f"/api/v1/courses/{course_id}/feedback", json=body,
                             headers={"Idempotency-Key": "fb-r1", "Origin": "http://testserver"})
    feedback_id = created.json()["data"]["feedback_id"]
    await api.post(
        f"/api/v1/courses/{course_id}/feedback/{feedback_id}/corrections",
        json={"expected_revision": 1, "text": "我认为正确的是……"},
        headers={"Idempotency-Key": "cor-r1", "Origin": "http://testserver"},
    )

    denied = await api.post(
        f"/api/v1/courses/{course_id}/feedback/{feedback_id}/reviews",
        json={"expected_revision": 1, "decision": "confirmed", "note": "普通用户不能确认"},
        headers={"Origin": "http://testserver"},
    )
    assert denied.status_code == 403

    stale = await api.post(
        f"/api/v1/courses/{course_id}/feedback/{feedback_id}/reviews",
        json={"expected_revision": 9, "decision": "confirmed", "note": "x"},
        headers={"Origin": "http://testserver"},
    )
    assert stale.status_code == 403  # evaluator gate 先于版本校验

    await execute("UPDATE users SET role='evaluator' WHERE id=%s", (owner,))
    confirmed = await api.post(
        f"/api/v1/courses/{course_id}/feedback/{feedback_id}/reviews",
        json={"expected_revision": 1, "decision": "confirmed", "note": "对照原文确认成立。"},
        headers={"Origin": "http://testserver"},
    )
    assert confirmed.status_code == 200, confirmed.text
    view = confirmed.json()["data"]
    assert view["provenance"] == "human_reviewer"
    assert view["confirmation"] == "confirmed"

    listing = await api.get(f"/api/v1/courses/{course_id}/feedback")
    item = listing.json()["data"]["items"][0]
    assert item["corrections"][-1]["confirmation"] == "confirmed"


@pytest.mark.asyncio
async def test_rejected_review_closes_feedback(learner):
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, [("cc1", "能解释参数", "recall", "参数", "ready")])
    course_id = course["course_id"]
    lesson_id = course["goals"]["cc1"]["lesson_id"]
    body = {"issue_kind": "content_error",
            "target": {"kind": "lesson", "lesson_id": lesson_id, "content_version": 1,
                       "block_index": 0},
            "comment": "疑似错误。"}
    created = await api.post(f"/api/v1/courses/{course_id}/feedback", json=body,
                             headers={"Idempotency-Key": "fb-rj", "Origin": "http://testserver"})
    feedback_id = created.json()["data"]["feedback_id"]
    await execute("UPDATE users SET role='evaluator' WHERE id=%s", (owner,))
    rejected = await api.post(
        f"/api/v1/courses/{course_id}/feedback/{feedback_id}/reviews",
        json={"expected_revision": 1, "decision": "rejected", "note": "原文无误。"},
        headers={"Origin": "http://testserver"},
    )
    assert rejected.status_code == 200, rejected.text
    listing = await api.get(f"/api/v1/courses/{course_id}/feedback")
    item = listing.json()["data"]["items"][0]
    assert item["status"] == "rejected"
    closed = await api.patch(
        f"/api/v1/courses/{course_id}/feedback/{feedback_id}",
        json={"expected_revision": 2, "status": "open"},
        headers={"Origin": "http://testserver"},
    )
    assert closed.status_code == 409


def test_correction_effect_matrix():
    assert correction_effect(provenance="learner_note", confirmation="confirmed",
                             target_kind="course_assessment") == "annotation_only"
    assert correction_effect(provenance="model_proposal", confirmation="provisional",
                             target_kind="course_assessment") == "annotation_only"
    assert correction_effect(provenance="human_reviewer", confirmation="confirmed",
                             target_kind="course_assessment") == "supersede_assessment"
    assert correction_effect(provenance="human_reviewer", confirmation="confirmed",
                             target_kind="quiz") == "request_new_check"
    assert correction_effect(provenance="human_reviewer", confirmation="confirmed",
                             target_kind="lesson") == "prepare_content_revision"


APPLICATION_CRITERIA = [
    ("cc_explanation", "解释返回值如何被调用处使用", "explanation", "返回值的用法", "ready"),
    ("cc_gap", "在真实项目里排查参数错误", "application", "参数排查", "material_gap"),
]


@pytest.mark.asyncio
async def test_application_regrade_supersedes_provisional_grade(personal_learner, course_worker):
    """owner+evaluator 复核：追加 human/confirmed 判分头，supersedes 暂定头并更新指针。"""
    api, session = personal_learner
    owner = session["user"]["id"]
    course = await published_course(owner, APPLICATION_CRITERIA)
    assessment_id = await _run_assessment(api, course_worker, course)
    detail = await _run_applications(api, course_worker, course, assessment_id)
    application = detail["applications"][0]
    saved = await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}"
        f"/applications/{application['application_task_id']}/attempts",
        headers={"Idempotency-Key": "cfa-1"},
        json={"expected_revision": application["revision"], "answer": "先分组再汇总，函数返回合计。",
              "help_usage": "none"},
    )
    assert saved.status_code == 201, saved.text
    attempt = saved.json()["data"]
    runner, _ = course_worker(application=ScriptedApplicationGenerator())
    assert await runner.run_once(task_id=attempt["feedback_task_id"])
    graded = (await api.get(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}"
        f"/attempts/{attempt['attempt_id']}")).json()["data"]
    provisional_id = graded["feedback"]["assessment_id"]
    attempt_revision = graded["revision"]
    assert graded["feedback"]["confirmation"] == "provisional"

    stale = await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}"
        f"/attempts/{attempt['attempt_id']}/reviews",
        json={"expected_assessment_id": provisional_id, "expected_revision": 99,
              "score": 0.5, "comment": "按固定 rubric 复核。"},
        headers={"Origin": "http://testserver"},
    )
    assert stale.status_code == 403  # evaluator gate

    await execute("UPDATE users SET role='evaluator' WHERE id=%s", (owner,))
    regraded = await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}"
        f"/attempts/{attempt['attempt_id']}/reviews",
        json={"expected_assessment_id": provisional_id, "expected_revision": attempt_revision,
              "score": 0.5, "comment": "按固定 rubric 复核：遗漏返回值说明。"},
        headers={"Origin": "http://testserver"},
    )
    assert regraded.status_code == 200, regraded.text
    view = regraded.json()["data"]
    assert view["confirmation"] == "confirmed"
    assert view["supersedes_assessment_id"] == provisional_id
    assert view["effect"] == "supersede_assessment"

    row = await fetch_one(
        "SELECT source,confirmation,score,supersedes_assessment_id FROM "
        "learning_course_application_assessments WHERE assessment_id=%s",
        (view["assessment_id"],),
    )
    assert row["source"] == "human" and row["confirmation"] == "confirmed"
    assert float(row["score"]) == 0.5
    pointer = await fetch_one(
        "SELECT latest_assessment_id FROM learning_course_application_attempts "
        "WHERE attempt_id=%s AND owner_id=%s",
        (attempt["attempt_id"], owner),
    )
    assert pointer["latest_assessment_id"] == view["assessment_id"]

    again = await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}"
        f"/attempts/{attempt['attempt_id']}/reviews",
        json={"expected_assessment_id": view["assessment_id"], "expected_revision": 1,
              "score": 1, "comment": "再次复核"},
        headers={"Origin": "http://testserver"},
    )
    assert again.status_code == 409
    assert again.json()["error_code"] == "regrade_already_confirmed"


async def _run_assessment(api, course_worker, course, *, key="b03-check"):
    queued = await api.post(
        f"/api/v1/courses/{course['course_id']}/assessment-jobs",
        headers={"Idempotency-Key": key},
        json={"expected_course_revision": 2, "expected_criteria_revision": 1},
    )
    assert queued.status_code == 202, queued.text
    view = queued.json()["data"]
    runner, _ = course_worker(application=ScriptedApplicationGenerator())
    assert await runner.run_once(task_id=view["task_id"])
    return view["course_assessment_id"]


async def _run_applications(api, course_worker, course, assessment_id, *, key="b03-apply"):
    queued = await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}/application-jobs",
        headers={"Idempotency-Key": key},
    )
    assert queued.status_code == 202, queued.text
    task_id = queued.json()["data"]["application_generation_task_id"]
    runner, _ = course_worker(application=ScriptedApplicationGenerator())
    assert await runner.run_once(task_id=task_id)
    detail = await api.get(f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}")
    assert detail.status_code == 200, detail.text
    return detail.json()["data"]
