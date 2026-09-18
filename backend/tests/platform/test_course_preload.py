"""纲要发布后预生成第一课：排队契约、可学课选择与纲要锁定。"""

import json
import uuid

import pytest
from app.core.db import execute, fetch_one
from app.core.errors import AppError
from app.core.values import dump, uid
from app.models.course import CourseOutlineUpdate
from app.rag.contracts import ResolvedScope
from app.services import course_service
from app.workers.course_job import _preload_first_lesson


def make_unit(title: str, availability: str = "available") -> dict:
    return {
        "unit_ref": "u" + uuid.uuid4().hex[:8],
        "title": title,
        "objective": "理解基本概念",
        "estimated_minutes": 10,
        "availability": availability,
    }


async def make_course(owner: int, units: list[dict], *, preload: bool = True):
    scope = ResolvedScope(owner_id=owner, namespace="production")
    course_id = uid("course")
    outline_task_id = uid("task")
    # learning_courses 的任务外键要求真实存在的 quiz_tasks 行。
    await execute(
        "INSERT INTO quiz_tasks(task_id,user_id,status,kind,operation,mode,user_input,request_json) "
        "VALUES(%s,%s,'completed','course_outline','course.outline','production','',%s)",
        (outline_task_id, owner, dump({"course_id": course_id})),
    )
    spec = {
        "topic": "测试主题",
        "goal": "",
        "prior_knowledge": "",
        "daily_minutes": 20,
        "timezone": "Asia/Shanghai",
        "lesson_count": len(units),
        "preload_first_lesson": preload,
        "source_policy": "topic",
        "scope": None,
    }
    await execute(
        "INSERT INTO learning_courses(course_id,owner_id,spec_json,source_policy,requested_scope_json,"
        "resolved_scope_json,scope_fingerprint,creation_task_id,outline_task_id,active_task_id,status,"
        "outline_json,revision) VALUES(%s,%s,%s,'topic',NULL,%s,%s,%s,%s,NULL,'ready',%s,2)",
        (
            course_id,
            owner,
            dump(spec),
            dump(scope.model_dump(mode="json")),
            scope.fingerprint,
            outline_task_id,
            outline_task_id,
            dump({"payload": {"title": "测试课程", "mission": None}, "sources": [], "warnings": []}),
        ),
    )
    lesson_ids = [uid("lesson") for _ in units]
    for lesson_id, position, unit in zip(lesson_ids, range(len(units)), units):
        await execute(
            "INSERT INTO learning_course_lessons(lesson_id,course_id,owner_id,unit_ref,position,"
            "unit_json,status,revision,content_version) VALUES(%s,%s,%s,%s,%s,%s,%s,1,0)",
            (
                lesson_id,
                course_id,
                owner,
                unit["unit_ref"],
                position,
                dump(unit),
                "material_gap" if unit["availability"] == "material_gap" else "not_generated",
            ),
        )
    return course_id, scope, lesson_ids


@pytest.mark.asyncio
async def test_preload_enqueues_first_generatable_lesson(personal_learner):
    api, session = personal_learner
    owner = session["user"]["id"]
    units = [make_unit("缺口课", "material_gap"), make_unit("可学课")]
    course_id, scope, lesson_ids = await make_course(owner, units)

    await _preload_first_lesson(
        None, {"user_id": owner}, {"course_id": course_id}, scope, units, lesson_ids, 2
    )

    target = await fetch_one(
        "SELECT status,generation_task_id,active_task_id FROM learning_course_lessons WHERE lesson_id=%s",
        (lesson_ids[1],),
    )
    assert target["status"] == "generating"
    assert target["generation_task_id"] == target["active_task_id"]
    skipped = await fetch_one(
        "SELECT status FROM learning_course_lessons WHERE lesson_id=%s", (lesson_ids[0],)
    )
    assert skipped["status"] == "material_gap"

    task = await fetch_one(
        "SELECT kind,operation,mode,status,request_json,idempotency_key FROM quiz_tasks WHERE task_id=%s",
        (target["generation_task_id"],),
    )
    assert task["kind"] == "course_lesson"
    assert task["operation"] == "course.lesson" and task["mode"] == "production"
    assert task["idempotency_key"] == f"course-preload:{course_id}:{lesson_ids[1]}"
    request = json.loads(task["request_json"])
    assert request["lesson_id"] == lesson_ids[1]
    assert request["expected_course_revision"] == 2


@pytest.mark.asyncio
async def test_preload_skipped_when_all_gap(learner):
    api, session = learner
    owner = session["user"]["id"]

    gap_units = [make_unit("缺口一", "material_gap"), make_unit("缺口二", "material_gap")]
    gap_course, scope, gap_ids = await make_course(owner, gap_units)
    await _preload_first_lesson(
        None, {"user_id": owner}, {"course_id": gap_course}, scope, gap_units, gap_ids, 2
    )
    row = await fetch_one(
        "SELECT status,generation_task_id FROM learning_course_lessons WHERE lesson_id=%s",
        (gap_ids[0],),
    )
    assert row["status"] == "material_gap" and row["generation_task_id"] is None


def test_preload_flag_defaults_on_and_survives_spec_roundtrip():
    """publish() 从 spec_json 读取开关：缺省开启、显式关闭保留。"""
    from app.core.values import load
    from app.models.course import CourseCreate

    assert CourseCreate(topic="主题").preload_first_lesson is True
    spec = CourseCreate(topic="主题", preload_first_lesson=False)
    restored = CourseCreate.model_validate(load(dump(spec.model_dump(mode="json"))))
    assert restored.preload_first_lesson is False


@pytest.mark.asyncio
async def test_preload_locks_outline_editing(personal_learner):
    api, session = personal_learner
    owner = session["user"]["id"]
    units = [make_unit("第一课")]
    course_id, scope, lesson_ids = await make_course(owner, units)
    await _preload_first_lesson(
        None, {"user_id": owner}, {"course_id": course_id}, scope, units, lesson_ids, 2
    )
    row = await fetch_one(
        "SELECT revision FROM learning_courses WHERE course_id=%s", (course_id,)
    )
    with pytest.raises(AppError) as locked:
        await course_service.update_outline(
            owner,
            course_id,
            CourseOutlineUpdate(expected_revision=row["revision"], title="改名"),
        )
    assert locked.value.code == "course_outline_locked"
