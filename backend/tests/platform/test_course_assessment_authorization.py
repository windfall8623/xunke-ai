"""结业Quiz与普通课程Quiz分开授权：撤销来源与失效会话必须阻断写入且不泄漏内容。"""

import pytest
from app.core.db import execute, fetch_all, fetch_one
from app.core.values import dump, uid
from app.rag.contracts import ResolvedScope, stable_hash

CRITERION_REF = "cc1"
LESSON_VERSION = 1


def _questions():
    return [
        {
            "id": f"q{index}",
            "type": "single",
            "stem": f"结业第{index}题",
            "options": [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
            "answer": ["A"],
            "explanation": "结业检查独立事实",
            "knowledge_point": f"目标{index}",
            "difficulty": "easy",
            "citation_refs": [],
            "course_criterion_refs": [CRITERION_REF],
        }
        for index in range(1, 4)
    ]


async def _task(owner, kind, *, quiz_id=None, status="completed", request=None):
    task_id = uid("task")
    await execute(
        "INSERT INTO quiz_tasks(task_id,user_id,status,kind,operation,mode,user_input,"
        "request_json,quiz_id) VALUES(%s,%s,%s,%s,%s,'production','',%s,%s)",
        (task_id, owner, status, kind, f"{kind}.generate", dump(request or {}), quiz_id),
    )
    return task_id


async def _quiz(owner, task_id, *, quiz_id=None):
    quiz_id = quiz_id or uid("quiz")
    await execute(
        "INSERT INTO quiz_sessions(quiz_id,user_id,title,summary,questions_json,"
        "source_status,source_policy,origin_task_id) "
        "VALUES(%s,%s,'结业检查','结业摘要',%s,'model_only','topic',%s)",
        (quiz_id, owner, dump(_questions()), task_id),
    )
    await execute("UPDATE quiz_tasks SET quiz_id=%s WHERE task_id=%s", (quiz_id, task_id))
    return quiz_id


async def _course(owner):
    """一门 topic 课程、一节已就绪课文与一个可检验目标。"""
    scope = ResolvedScope(owner_id=owner, namespace="production")
    course_id, lesson_id = uid("course"), uid("lesson")
    outline_task = await _task(owner, "course_outline", request={"course_id": course_id})
    unit = {
        "unit_ref": "u1", "title": "输入与输出", "objective": "解释函数参数与返回值",
        "estimated_minutes": 10, "availability": "available",
    }
    await execute(
        "INSERT INTO learning_courses(course_id,owner_id,spec_json,source_policy,requested_scope_json,"
        "resolved_scope_json,scope_fingerprint,creation_task_id,outline_task_id,status,outline_json,"
        "revision,criteria_revision) VALUES(%s,%s,%s,'topic',NULL,%s,%s,%s,%s,'ready',%s,2,1)",
        (course_id, owner, dump({"topic": "函数", "timezone": "Asia/Shanghai"}),
         dump(scope), scope.fingerprint, outline_task, outline_task,
         dump({"payload": {"title": "函数入门", "mission": None}, "sources": [], "warnings": []})),
    )
    content = {"payload": {"objective": unit["objective"], "blocks": [
        {"type": "explanation", "text": "参数接收输入，return 交回结果。", "source_refs": []},
        {"type": "recap", "text": "按输入、计算、返回值追踪函数。", "source_refs": []},
    ]}, "sources": [], "warnings": []}
    await execute(
        "INSERT INTO learning_course_lessons(lesson_id,course_id,owner_id,unit_ref,position,"
        "unit_json,content_json,status,revision,content_version) "
        "VALUES(%s,%s,%s,'u1',0,%s,%s,'ready',2,%s)",
        (lesson_id, course_id, owner, dump(unit), dump(content), LESSON_VERSION),
    )
    criterion_id = uid("ccrit")
    definition = {"course_criterion_ref": CRITERION_REF, "description": "解释函数参数与返回值",
                  "evidence_type": "recognition", "expectation": "换一组输入说明返回值"}
    await execute(
        "INSERT INTO learning_course_criteria(course_criterion_id,criteria_revision,course_id,owner_id,"
        "course_criterion_ref,position,description,evidence_type,expectation,definition_hash,"
        "lesson_ids_json,requirements_json,origin) "
        "VALUES(%s,1,%s,%s,%s,0,%s,'recognition',%s,%s,%s,%s,'generated_v2')",
        (criterion_id, course_id, owner, CRITERION_REF, definition["description"],
         definition["expectation"], stable_hash(definition), dump([lesson_id]), dump({})),
    )
    return dict(course_id=course_id, lesson_id=lesson_id, criterion_id=criterion_id,
                scope=scope, definition_hash=stable_hash(definition))


async def _assessment(owner, course, *, status="ready"):
    """冻结一次结业范围，并按已发布题目写入目标映射。"""
    criterion = {
        "course_criterion_id": course["criterion_id"], "course_criterion_ref": CRITERION_REF,
        "criteria_revision": 1, "description": "解释函数参数与返回值",
        "evidence_type": "recognition", "expectation": "换一组输入说明返回值",
        "lesson_ids": [course["lesson_id"]], "origin": "generated_v2",
        "definition_hash": course["definition_hash"],
        "lesson_versions": {course["lesson_id"]: LESSON_VERSION}, "available": True,
    }
    snapshot = dict(source_policy="topic", criteria=[criterion],
                    selected_criterion_ids=[course["criterion_id"]],
                    quiz_criterion_ids=[course["criterion_id"]],
                    lesson_context=[], lesson_evidence={})
    task_id = await _task(owner, "quiz")
    quiz_id = await _quiz(owner, task_id)
    assessment_id = uid("course_assessment")
    await execute(
        "INSERT INTO learning_course_assessments(course_assessment_id,course_id,owner_id,criteria_revision,"
        "course_revision,source_policy,scope_json,scope_fingerprint,snapshot_json,task_id,quiz_id,status,"
        "idempotency_key,request_hash) VALUES(%s,%s,%s,1,2,'topic',%s,%s,%s,%s,%s,%s,%s,%s)",
        (assessment_id, course["course_id"], owner, dump(course["scope"]), course["scope"].fingerprint,
         dump(snapshot), task_id, quiz_id, status, uid("key"), stable_hash({"assessment": assessment_id})),
    )
    for question in _questions():
        await execute(
            "INSERT INTO learning_course_assessment_questions(course_assessment_id,course_id,owner_id,"
            "quiz_id,question_id,question_version,course_criterion_id,criteria_revision) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,1)",
            (assessment_id, course["course_id"], owner, quiz_id, question["id"],
             stable_hash(question), course["criterion_id"]),
        )
    return assessment_id, quiz_id


async def _ordinary_course_quiz(owner, course):
    """普通课时Quiz走既有 lesson_link 路径，与结业身份互不影响。"""
    task_id = await _task(owner, "quiz")
    quiz_id = await _quiz(owner, task_id)
    await execute(
        "INSERT INTO learning_course_quiz_links(link_id,course_id,lesson_id,owner_id,task_id,kind,"
        "content_version) VALUES(%s,%s,%s,%s,%s,'initial',%s)",
        (uid("cql"), course["course_id"], course["lesson_id"], owner, task_id, LESSON_VERSION),
    )
    return quiz_id


async def _answer(api, quiz_id, question_id="q1", selected=("A",)):
    return await api.put(f"/api/v1/quiz/{quiz_id}/answers/{question_id}",
                         json={"selected_answers": list(selected), "duration_ms": 120})


async def _answer_all(api, quiz_id):
    for question in _questions():
        result = await _answer(api, quiz_id, question["id"])
        assert result.status_code == 200, result.text


def _leaks_nothing(payload):
    return (payload["questions"] == [] and payload["source_status"] == "source_revoked"
            and payload["summary"] == "" and payload["title"] == "资料已失效的练习"
            and payload["answer_records"] == [] and payload["course_context"] is None)


@pytest.mark.asyncio
async def test_revoked_source_blocks_assessment_answer_and_leaks_no_content(learner):
    """来源撤销后结业题不能作答，读取也不返回课时或题目内容。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await _course(owner)
    _, quiz_id = await _assessment(owner, course)
    assert (await _answer(api, quiz_id)).status_code == 200

    # 课程资料被撤销：既有 purge 路径清空 resolved_scope 并置 source_revoked。
    await execute(
        "UPDATE learning_courses SET status='source_revoked',resolved_scope_json=NULL "
        "WHERE course_id=%s AND owner_id=%s", (course["course_id"], owner),
    )
    blocked = await _answer(api, quiz_id, "q2")
    assert blocked.status_code == 404 and blocked.json()["error_code"] == "source_revoked"
    detail = await api.get(f"/api/v1/user/quizzes/{quiz_id}")
    assert detail.status_code == 200 and _leaks_nothing(detail.json()["data"])
    settle = await api.post(f"/api/v1/quiz/{quiz_id}/complete", json={"expected_revision": 1})
    assert settle.status_code == 404 and settle.json()["error_code"] == "source_revoked"
    # 阻断发生在读取任何题目事实之前：没有结算，也没有 XP。
    quiz = await fetch_one("SELECT status,settled_at,xp_awarded FROM quiz_sessions WHERE quiz_id=%s", (quiz_id,))
    assert quiz["status"] == "active" and quiz["settled_at"] is None and quiz["xp_awarded"] == 0


@pytest.mark.asyncio
async def test_revoked_assessment_session_blocks_write(learner):
    """结业会话被清理（快照作废）后不能继续作答或结算。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await _course(owner)
    assessment_id, quiz_id = await _assessment(owner, course)
    await execute(
        "UPDATE learning_course_assessments SET snapshot_json=NULL,scope_json=NULL,"
        "status='source_revoked',revoked_at=UTC_TIMESTAMP(6) WHERE course_assessment_id=%s",
        (assessment_id,),
    )
    blocked = await _answer(api, quiz_id)
    assert blocked.status_code == 404 and blocked.json()["error_code"] == "source_revoked"
    detail = await api.get(f"/api/v1/user/quizzes/{quiz_id}")
    assert detail.status_code == 200 and _leaks_nothing(detail.json()["data"])


@pytest.mark.asyncio
async def test_stale_lesson_version_blocks_assessment_write(learner):
    """冻结范围内的课文改版后，结业写入被 revision_conflict 阻断。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await _course(owner)
    _, quiz_id = await _assessment(owner, course)
    await execute(
        "UPDATE learning_course_lessons SET content_version=content_version+1 "
        "WHERE lesson_id=%s AND owner_id=%s", (course["lesson_id"], owner),
    )
    stale = await _answer(api, quiz_id)
    assert stale.status_code == 409 and stale.json()["error_code"] == "revision_conflict"
    settle = await api.post(f"/api/v1/quiz/{quiz_id}/complete", json={"expected_revision": 0})
    assert settle.status_code == 409 and settle.json()["error_code"] == "revision_conflict"
    answers = await fetch_all("SELECT question_id FROM quiz_answers WHERE quiz_id=%s", (quiz_id,))
    assert not answers


@pytest.mark.asyncio
async def test_revoked_criteria_definition_blocks_assessment_write(learner):
    """目标定义变化视为另一组检查，冻结会话不再可写。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await _course(owner)
    _, quiz_id = await _assessment(owner, course)
    await execute(
        "UPDATE learning_course_criteria SET definition_hash=%s WHERE course_criterion_id=%s",
        (stable_hash({"changed": True}), course["criterion_id"]),
    )
    changed = await _answer(api, quiz_id)
    assert changed.status_code == 409 and changed.json()["error_code"] == "revision_conflict"


@pytest.mark.asyncio
async def test_ordinary_course_quiz_keeps_existing_path(learner):
    """普通课时Quiz不受结业授权影响：撤销结业会话不改变其读写。"""
    api, session = learner
    owner = session["user"]["id"]
    course = await _course(owner)
    assessment_id, assessment_quiz = await _assessment(owner, course)
    ordinary = await _ordinary_course_quiz(owner, course)
    await execute(
        "UPDATE learning_course_assessments SET snapshot_json=NULL,status='source_revoked',"
        "revoked_at=UTC_TIMESTAMP(6) WHERE course_assessment_id=%s", (assessment_id,),
    )
    assert (await _answer(api, assessment_quiz)).status_code == 404

    detail = await api.get(f"/api/v1/user/quizzes/{ordinary}")
    assert detail.status_code == 200
    payload = detail.json()["data"]
    assert len(payload["questions"]) == 3
    assert payload["course_context"]["lesson_id"] == course["lesson_id"]
    await _answer_all(api, ordinary)
    settled = await api.post(f"/api/v1/quiz/{ordinary}/complete", json={"expected_revision": 3})
    assert settled.status_code == 200 and settled.json()["data"]["xp_awarded"] == 16
    # 普通课程Quiz的结算不写入任何结业目标证据。
    facts = await fetch_all(
        "SELECT settlement_json FROM learning_course_assessment_questions WHERE owner_id=%s", (owner,),
    )
    assert [item["settlement_json"] for item in facts] == [None, None, None]


@pytest.mark.asyncio
async def test_assessment_settlement_stays_idempotent(learner):
    """结算与封存都可重放：不重复授予 XP，也不二次写入目标证据。"""
    api, session = learner
    from app.models.course_assessment import CourseAssessmentComplete
    from app.services import course_assessment_service as assessments

    owner = session["user"]["id"]
    course = await _course(owner)
    assessment_id, quiz_id = await _assessment(owner, course)
    await _answer_all(api, quiz_id)
    first = await api.post(f"/api/v1/quiz/{quiz_id}/complete", json={"expected_revision": 3})
    assert first.status_code == 200 and first.json()["data"]["xp_awarded"] == 16
    replay = await api.post(f"/api/v1/quiz/{quiz_id}/complete", json={"expected_revision": 0})
    assert replay.status_code == 200 and replay.json()["data"] == first.json()["data"]
    user = await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,))
    assert user["total_xp"] == 16

    body = CourseAssessmentComplete(expected_revision=1)
    key = uid("complete")
    sealed = await assessments.complete_course_assessment(owner, course["course_id"], assessment_id, body, key)
    assert sealed["status"] == "completed" and sealed["quiz_settled"] is True
    stamps = await fetch_all(
        "SELECT question_id,settled_at,settlement_json FROM learning_course_assessment_questions "
        "WHERE course_assessment_id=%s ORDER BY question_id", (assessment_id,),
    )
    assert len(stamps) == 3 and all(item["settlement_json"] for item in stamps)
    again = await assessments.complete_course_assessment(owner, course["course_id"], assessment_id, body, key)
    assert again["status"] == "completed"
    repeat = await fetch_all(
        "SELECT question_id,settled_at,settlement_json FROM learning_course_assessment_questions "
        "WHERE course_assessment_id=%s ORDER BY question_id", (assessment_id,),
    )
    assert repeat == stamps
    user = await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,))
    assert user["total_xp"] == 16


@pytest.mark.asyncio
async def test_assessment_quiz_stays_owner_isolated(learner):
    """另一账号不能读取或作答他人的结业Quiz。"""
    from tests.platform.conftest import register_email_account

    api, session = learner
    owner = session["user"]["id"]
    course = await _course(owner)
    _, quiz_id = await _assessment(owner, course)
    other, _ = await register_email_account(api, nickname="其他学习者")
    api.headers.update({"X-CSRF-Token": other["csrf_token"], "Origin": "http://testserver"})
    assert (await api.get(f"/api/v1/user/quizzes/{quiz_id}")).status_code == 404
    assert (await _answer(api, quiz_id)).status_code == 404
