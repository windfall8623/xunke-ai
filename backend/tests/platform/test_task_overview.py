"""跨页面任务通知的数据源：GET /tasks/active 的范围与过滤。"""

import uuid

import pytest
from app.core.db import execute
from app.core.values import dump, uid


async def insert_task(owner: int, *, kind: str, status: str, minutes_ago: int = 0):
    task_id = uid("task")
    await execute(
        "INSERT INTO quiz_tasks(task_id,user_id,status,kind,operation,mode,user_input,request_json,"
        "created_at,updated_at) VALUES(%s,%s,%s,%s,%s,'production',%s,%s,"
        "UTC_TIMESTAMP(6) - INTERVAL %s MINUTE,UTC_TIMESTAMP(6) - INTERVAL %s MINUTE)",
        (
            task_id,
            owner,
            status,
            kind,
            kind + ".op",
            "练习主题" if kind in {"quiz", "practice_generate"} else "",
            dump({"course_id": "course_" + uuid.uuid4().hex[:8]}),
            minutes_ago,
            minutes_ago,
        ),
    )
    return task_id


@pytest.mark.asyncio
async def test_active_overview_filters_window_kinds_and_scopes_owner(learner):
    api, session = learner
    owner = session["user"]["id"]

    pending_outline = await insert_task(owner, kind="course_outline", status="pending")
    done_quiz = await insert_task(owner, kind="quiz", status="completed")
    failed_report = await insert_task(
        owner, kind="report", status="failed", minutes_ago=30
    )
    await insert_task(owner, kind="qa", status="pending")
    await insert_task(owner, kind="course_tutor", status="running")
    await insert_task(owner, kind="quiz", status="completed", minutes_ago=240)

    response = await api.get("/api/v1/tasks/active")
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    task_ids = {item["task_id"] for item in data["tasks"]}
    assert pending_outline in task_ids and done_quiz in task_ids
    assert failed_report not in task_ids, "窗口外的终态任务不应进入通知源"
    kinds = {item["task_id"]: item["kind"] for item in data["tasks"]}
    assert "qa" not in kinds.values() and "course_tutor" not in kinds.values()
    quiz_item = next(item for item in data["tasks"] if item["task_id"] == done_quiz)
    assert quiz_item["title"] == "练习主题"
    outline_item = next(item for item in data["tasks"] if item["task_id"] == pending_outline)
    assert outline_item["course_id"]


@pytest.mark.asyncio
async def test_active_overview_lists_processing_documents(learner):
    api, session = learner
    owner = session["user"]["id"]
    doc_id = "doc_" + uuid.uuid4().hex[:12]
    await execute(
        "INSERT INTO kb_documents(doc_id,user_id,file_name,file_type,file_size,status,purpose) "
        "VALUES(%s,%s,'讲义.pdf','pdf',1024,'processing','production')",
        (doc_id, owner),
    )
    await execute(
        "INSERT INTO kb_documents(doc_id,user_id,file_name,file_type,file_size,status,purpose) "
        "VALUES(%s,%s,'旧资料.txt','txt',128,'ready','production')",
        ("doc_" + uuid.uuid4().hex[:12], owner),
    )
    response = await api.get("/api/v1/tasks/active")
    assert response.status_code == 200, response.text
    documents = response.json()["data"]["documents"]
    assert [item["doc_id"] for item in documents] == [doc_id]
    assert documents[0]["file_name"] == "讲义.pdf"
