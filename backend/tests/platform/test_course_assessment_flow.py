"""A07 结业检查的 HTTP 全链路：目标映射、结算证据与「完成不等于已验证」。

场景 V05：从 POST assessment-jobs 到 complete，检查题目与 course_criterion_id
的持久映射、未覆盖目标可见、只有已结算且确认的证据进入目标投影，以及暂定或
帮助未知永不显示已验证。授权/撤销边界仍由 test_course_assessment_authorization.py 覆盖。
"""

import pytest
from app.core.db import fetch_all, fetch_one

from tests.platform.course_assessment_helpers import (  # noqa: F401 - course_worker fixture
    ScriptedQuizGenerator, course_worker, published_course,
)

# 两个已教目标（一个识记、一个表达）加一个资料缺口目标。
CRITERIA = [
    ("cc_recognition", "识别函数的参数与返回值", "recognition", "输入与输出", "ready"),
    ("cc_explanation", "解释返回值如何被调用处使用", "explanation", "返回值的用法", "ready"),
    ("cc_gap", "在真实项目里排查参数错误", "application", "参数排查", "material_gap"),
]


async def _create(api, course, *, key, criterion_ids=None):
    return await api.post(
        f"/api/v1/courses/{course['course_id']}/assessment-jobs",
        headers={"Idempotency-Key": key},
        json={"expected_course_revision": 2, "expected_criteria_revision": 1,
              **({"course_criterion_ids": criterion_ids} if criterion_ids is not None else {})},
    )


async def _ready_assessment(api, course_worker, course, *, key="a07-check", generator=None):
    """Create one frozen check and let the leased worker publish its quiz."""
    queued = await _create(api, course, key=key)
    assert queued.status_code == 202, queued.text
    view = queued.json()["data"]
    assert view["status"] == "generating" and view["quiz_id"] is None
    runner, generator = course_worker(generator)
    assert await runner.run_once(task_id=view["task_id"])
    detail = await api.get(
        f"/api/v1/courses/{course['course_id']}/assessments/{view['course_assessment_id']}")
    assert detail.status_code == 200, detail.text
    return detail.json()["data"], generator


async def _answer_all(api, quiz_id, *, wrong=()):
    detail = await api.get(f"/api/v1/user/quizzes/{quiz_id}")
    assert detail.status_code == 200, detail.text
    for question in detail.json()["data"]["questions"]:
        selected = ["B"] if question["id"] in set(wrong) else ["A"]
        saved = await api.put(f"/api/v1/quiz/{quiz_id}/answers/{question['id']}",
                              json={"selected_answers": selected, "duration_ms": 150})
        assert saved.status_code == 200, saved.text
    return detail.json()["data"]["questions"]


async def _settle(api, quiz_id, questions):
    result = await api.post(f"/api/v1/quiz/{quiz_id}/complete",
                            json={"expected_revision": len(questions)})
    assert result.status_code == 200, result.text
    return result.json()["data"]


async def _complete(api, course, assessment_id, *, revision, help_usage, key):
    return await api.post(
        f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}/complete",
        headers={"Idempotency-Key": key},
        json={"expected_revision": revision, "help_usage": help_usage},
    )


def _outcome(summary, criterion_id):
    return next(item for item in summary["criteria"] if item["course_criterion_id"] == criterion_id)


@pytest.mark.asyncio
async def test_assessment_maps_questions_to_goals_and_reports_uncovered(learner, course_worker):
    """题目映射按发布产物落库；资料缺口目标可见但不被本组检查覆盖。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    view, generator = await _ready_assessment(api, course_worker, course)
    taught = [course["goals"][ref]["course_criterion_id"] for ref in ("cc_recognition", "cc_explanation")]
    gap = course["goals"]["cc_gap"]["course_criterion_id"]

    assert view["status"] == "ready" and view["quiz_id"] and generator.calls == 1
    assert view["covered_course_criterion_ids"] == sorted(taught)
    # 缺口目标既不进入客观题，也不因为「已创建检查」而被算作已覆盖。
    assert view["uncovered_course_criterion_ids"] == [gap]

    mapping = await fetch_all(
        "SELECT question_id,course_criterion_id,question_version,criteria_revision,settlement_json "
        "FROM learning_course_assessment_questions WHERE course_assessment_id=%s ORDER BY question_id",
        (view["course_assessment_id"],),
    )
    quiz = await fetch_one("SELECT questions_json FROM quiz_sessions WHERE quiz_id=%s", (view["quiz_id"],))
    from app.core.values import load
    from app.services.course_assessment_service import objective_question_version

    questions = {item["id"]: item for item in load(quiz["questions_json"])}
    assert len(mapping) == len(questions) == 4
    for row in mapping:
        assert row["course_criterion_id"] in taught and row["criteria_revision"] == 1
        # 映射绑定题目内容身份，且结算前没有任何证据。
        assert row["question_version"] == objective_question_version(questions[row["question_id"]])
        assert row["settlement_json"] is None
    assert {row["course_criterion_id"] for row in mapping} == set(taught)
    # 只读投影不因为存在检查而产生已验证结果。
    summary = await api.get(f"/api/v1/courses/{course['course_id']}/outcomes")
    assert summary.status_code == 200, summary.text
    assert {item["status"] for item in summary.json()["data"]["criteria"]} == {"unverified"}


@pytest.mark.asyncio
async def test_completed_check_does_not_verify_every_goal(learner, course_worker):
    """结业「已完成」只说明本组检查已封存：未覆盖与非识记目标仍待验证。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    view, _ = await _ready_assessment(api, course_worker, course)
    assessment_id, quiz_id = view["course_assessment_id"], view["quiz_id"]
    questions = await _answer_all(api, quiz_id)
    await _settle(api, quiz_id, questions)

    current = await api.get(f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}")
    sealed = await _complete(api, course, assessment_id, revision=current.json()["data"]["revision"],
                             help_usage="none", key="a07-complete")
    assert sealed.status_code == 200, sealed.text
    assert sealed.json()["data"]["status"] == "completed"
    assert sealed.json()["data"]["quiz_settled"] is True

    summary = (await api.get(f"/api/v1/courses/{course['course_id']}/outcomes")).json()["data"]
    recognition = _outcome(summary, course["goals"]["cc_recognition"]["course_criterion_id"])
    explanation = _outcome(summary, course["goals"]["cc_explanation"]["course_criterion_id"])
    gap = _outcome(summary, course["goals"]["cc_gap"]["course_criterion_id"])
    # 识记目标由客观题独立确认；同一组题不能验证表达或应用型目标。
    assert recognition["status"] == "verified" and recognition["evidence_refs"]
    assert explanation["status"] == "unverified" and explanation["evidence_refs"]
    assert "题型" in explanation["reason"]
    assert gap["status"] == "unverified" and gap["evidence_refs"] == []
    assert "资料缺口" in gap["reason"]


@pytest.mark.asyncio
async def test_confirmed_wrong_answer_asks_for_practice(learner, course_worker):
    """一题确认错误 → 该目标显示需补学，不因其他题正确而抵消。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    view, _ = await _ready_assessment(api, course_worker, course)
    assessment_id, quiz_id = view["course_assessment_id"], view["quiz_id"]
    recognition = course["goals"]["cc_recognition"]["course_criterion_id"]
    mapped = await fetch_all(
        "SELECT question_id FROM learning_course_assessment_questions WHERE course_assessment_id=%s "
        "AND course_criterion_id=%s ORDER BY question_id", (assessment_id, recognition),
    )
    questions = await _answer_all(api, quiz_id, wrong=[mapped[0]["question_id"]])
    await _settle(api, quiz_id, questions)
    current = await api.get(f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}")
    sealed = await _complete(api, course, assessment_id, revision=current.json()["data"]["revision"],
                             help_usage="none", key="a07-wrong")
    assert sealed.status_code == 200, sealed.text
    summary = (await api.get(f"/api/v1/courses/{course['course_id']}/outcomes")).json()["data"]
    outcome = _outcome(summary, recognition)
    assert outcome["status"] == "needs_practice" and "补练" in outcome["reason"]


@pytest.mark.asyncio
async def test_unknown_help_usage_keeps_grade_without_verification(learner, course_worker):
    """帮助情况未知时保留成绩，但不显示已验证。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    view, _ = await _ready_assessment(api, course_worker, course)
    assessment_id, quiz_id = view["course_assessment_id"], view["quiz_id"]
    questions = await _answer_all(api, quiz_id)
    receipt = await _settle(api, quiz_id, questions)
    assert receipt["accuracy"] == 100

    current = await api.get(f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}")
    sealed = await _complete(api, course, assessment_id, revision=current.json()["data"]["revision"],
                             help_usage="unknown", key="a07-unknown")
    assert sealed.status_code == 200, sealed.text
    summary = (await api.get(f"/api/v1/courses/{course['course_id']}/outcomes")).json()["data"]
    outcome = _outcome(summary, course["goals"]["cc_recognition"]["course_criterion_id"])
    assert outcome["status"] == "unverified"
    assert "帮助使用情况未知" in outcome["reason"] and outcome["evidence_refs"]
    stored = await fetch_one(
        "SELECT completion_json FROM learning_course_assessments WHERE course_assessment_id=%s",
        (assessment_id,),
    )
    from app.core.values import load

    completion = load(stored["completion_json"])
    assert completion["help_usage"] == "unknown"
    assert completion["help_usage_source"] == "unknown"


@pytest.mark.asyncio
async def test_outcomes_ignore_answers_until_the_quiz_is_settled(learner, course_worker):
    """未结算的回答不是学习事实：投影不读取它，也不产生成绩证据。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    view, _ = await _ready_assessment(api, course_worker, course)
    await _answer_all(api, view["quiz_id"])
    summary = (await api.get(f"/api/v1/courses/{course['course_id']}/outcomes")).json()["data"]
    assert all(item["status"] == "unverified" and item["evidence_refs"] == []
               for item in summary["criteria"])
    # 结算后但封存前：证据可见，但必要检查尚未全部完成。
    questions = await _answer_all(api, view["quiz_id"])
    await _settle(api, view["quiz_id"], questions)
    summary = (await api.get(f"/api/v1/courses/{course['course_id']}/outcomes")).json()["data"]
    outcome = _outcome(summary, course["goals"]["cc_recognition"]["course_criterion_id"])
    assert outcome["status"] == "unverified" and outcome["evidence_refs"]
    assert "尚未全部完成" in outcome["reason"]


@pytest.mark.asyncio
async def test_idempotent_create_never_opens_a_second_session(learner, course_worker):
    """同一 Idempotency-Key 重放只有一组会话、一个任务和一份题目映射。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    view, generator = await _ready_assessment(api, course_worker, course, key="a07-replay")
    replay = await _create(api, course, key="a07-replay")
    assert replay.status_code == 202, replay.text
    assert replay.json()["data"]["course_assessment_id"] == view["course_assessment_id"]
    assert replay.json()["data"]["quiz_id"] == view["quiz_id"]
    assert generator.calls == 1

    sessions = await fetch_all(
        "SELECT course_assessment_id,task_id FROM learning_course_assessments WHERE owner_id=%s "
        "AND course_id=%s", (owner, course["course_id"]),
    )
    assert len(sessions) == 1
    tasks = await fetch_all("SELECT task_id FROM quiz_tasks WHERE user_id=%s AND kind='quiz'", (owner,))
    assert len(tasks) == 1
    quizzes = await fetch_all("SELECT quiz_id FROM quiz_sessions WHERE user_id=%s", (owner,))
    assert len(quizzes) == 1
    mapping = await fetch_all(
        "SELECT question_id FROM learning_course_assessment_questions WHERE owner_id=%s", (owner,))
    assert len(mapping) == 4
    # 相同标识、不同请求必须报冲突，不静默复用已有会话。
    conflict = await _create(api, course, key="a07-replay",
                            criterion_ids=[course["goals"]["cc_recognition"]["course_criterion_id"]])
    assert conflict.status_code == 409 and conflict.json()["error_code"] == "idempotency_conflict"


@pytest.mark.asyncio
async def test_completion_requires_settled_quiz_and_replays_once(learner, course_worker):
    """未结算不能封存；封存可重放且不重复写入结算证据或 XP。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    view, _ = await _ready_assessment(api, course_worker, course)
    assessment_id, quiz_id = view["course_assessment_id"], view["quiz_id"]
    early = await _complete(api, course, assessment_id, revision=view["revision"],
                            help_usage="none", key="a07-early")
    assert early.status_code == 409
    assert early.json()["error_code"] == "course_assessment_incomplete"

    questions = await _answer_all(api, quiz_id)
    await _settle(api, quiz_id, questions)
    current = await api.get(f"/api/v1/courses/{course['course_id']}/assessments/{assessment_id}")
    revision = current.json()["data"]["revision"]
    first = await _complete(api, course, assessment_id, revision=revision,
                            help_usage="none", key="a07-seal")
    assert first.status_code == 200, first.text
    stamps = await fetch_all(
        "SELECT question_id,settled_at,settlement_json FROM learning_course_assessment_questions "
        "WHERE course_assessment_id=%s ORDER BY question_id", (assessment_id,),
    )
    assert len(stamps) == 4 and all(item["settlement_json"] for item in stamps)
    user = await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,))

    replay = await _complete(api, course, assessment_id, revision=revision,
                             help_usage="none", key="a07-seal")
    assert replay.status_code == 200 and replay.json()["data"] == first.json()["data"]
    assert await fetch_all(
        "SELECT question_id,settled_at,settlement_json FROM learning_course_assessment_questions "
        "WHERE course_assessment_id=%s ORDER BY question_id", (assessment_id,),
    ) == stamps
    assert (await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,))) == user
    # 另一个操作标识不能重复封存同一组检查。
    again = await _complete(api, course, assessment_id, revision=revision,
                            help_usage="none", key="a07-seal-other")
    assert again.status_code == 409
    assert again.json()["error_code"] == "course_assessment_completed"


@pytest.mark.asyncio
async def test_unmapped_generated_question_blocks_publication(learner, course_worker):
    """题目缺少有效课程目标对应时不发布：没有会话题目映射，也没有猜测覆盖。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA)
    queued = await _create(api, course, key="a07-unmapped")
    assert queued.status_code == 202, queued.text
    view = queued.json()["data"]
    runner, _ = course_worker(ScriptedQuizGenerator(refs_for=lambda target: []))
    assert await runner.run_once(task_id=view["task_id"])
    task = await fetch_one("SELECT status,error_code FROM quiz_tasks WHERE task_id=%s", (view["task_id"],))
    assert task["status"] == "failed"
    assert not await fetch_all(
        "SELECT question_id FROM learning_course_assessment_questions WHERE owner_id=%s", (owner,))
    assert not await fetch_all("SELECT quiz_id FROM quiz_sessions WHERE user_id=%s", (owner,))
    detail = await api.get(
        f"/api/v1/courses/{course['course_id']}/assessments/{view['course_assessment_id']}")
    assert detail.status_code == 200 and detail.json()["data"]["status"] == "failed"
    assert detail.json()["data"]["covered_course_criterion_ids"] == []


@pytest.mark.asyncio
async def test_goal_identity_preserves_evidence_when_local_ref_changes(learner, course_worker):
    """局部 ref 改名不能抹掉同一目标的成绩；真正的课文改版仍使证据过期。"""
    from app.core.db import execute, transaction
    from app.core.values import dump, load
    from app.services.course_outcome_service import publish_course_criteria

    api, session = learner
    owner = session["user"]["id"]
    course = await published_course(owner, CRITERIA[:1])
    view, _ = await _ready_assessment(api, course_worker, course)
    questions = await _answer_all(api, view["quiz_id"])
    await _settle(api, view["quiz_id"], questions)
    current = (await api.get(
        f"/api/v1/courses/{course['course_id']}/assessments/{view['course_assessment_id']}"
    )).json()["data"]
    sealed = await _complete(api, course, view["course_assessment_id"], revision=current["revision"],
                             help_usage="none", key="a07-identity-complete")
    assert sealed.status_code == 200, sealed.text

    goal = course["goals"]["cc_recognition"]
    definition = await fetch_one(
        "SELECT * FROM learning_course_criteria WHERE course_criterion_id=%s AND criteria_revision=1",
        (goal["course_criterion_id"],))
    lesson = await fetch_one("SELECT unit_json FROM learning_course_lessons WHERE lesson_id=%s",
                             (goal["lesson_id"],))
    unit = load(lesson["unit_json"])
    renamed_ref = "cc_function_input_output"
    unit["course_criterion_refs"] = [renamed_ref]
    # The publication path decides that the definition and lesson dependencies
    # are unchanged, and therefore retains the formal course_criterion_id.
    async with transaction() as conn:
        await execute("UPDATE learning_course_lessons SET unit_json=%s WHERE lesson_id=%s",
                      (dump(unit), goal["lesson_id"]), conn=conn)
        published = await publish_course_criteria(conn, owner, course["course_id"], {
            "schema_version": "xunke-teach.v2", "payload": {"course_criteria": [{
                "course_criterion_ref": renamed_ref,
                **{key: definition[key] for key in ("description", "evidence_type", "expectation")},
            }]},
        })
    assert published[0].course_criterion_id == goal["course_criterion_id"]
    assert published[0].criteria_revision == 2

    outcome = (await api.get(f"/api/v1/courses/{course['course_id']}/outcomes")).json()["data"]
    unchanged = _outcome(outcome, goal["course_criterion_id"])
    assert unchanged["status"] == "verified"
    assert unchanged["evidence_refs"][0]["origin_id"] == view["quiz_id"]

    await execute("UPDATE learning_course_lessons SET content_version=content_version+1 WHERE lesson_id=%s",
                  (goal["lesson_id"],))
    outcome = (await api.get(f"/api/v1/courses/{course['course_id']}/outcomes")).json()["data"]
    assert _outcome(outcome, goal["course_criterion_id"])["status"] == "stale"
