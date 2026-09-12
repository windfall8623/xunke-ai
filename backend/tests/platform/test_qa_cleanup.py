"""Real MySQL concurrency: old-scope cleanup and a new-scope submission."""

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar

import pytest

from tests.platform.qa_helpers import ask, new_session
from tests.platform.qa_helpers import qa_context as qa_context
from tests.platform.test_qa_worker import install_answer_provider


@pytest.mark.asyncio
async def test_cleanup_and_new_revision_question_commit_without_deadlock(
    qa_context, monkeypatch
):
    from app.core.db import fetch_one
    from app.core.values import load
    from app.services import qa_read, qa_service

    ctx = qa_context
    install_answer_provider(ctx, monkeypatch)
    session = await new_session(ctx)
    original = (await ask(ctx, session)).json()["data"]
    await ctx["worker"].run_once(task_id=original["task_id"])
    original = (await ctx["api"].get(f"/api/v1/qa/tasks/{original['task_id']}")).json()[
        "data"
    ]
    assert original["status"] == "completed", original
    answer_id = original["answer"]["answer_id"]
    feedback = await ctx["api"].post(
        f"/api/v1/qa/answers/{answer_id}/feedback",
        json={
            "rating": "helpful",
            "comment": "旧资料的文本",
            "evaluation_consent": True,
        },
    )
    assert feedback.status_code == 200
    upload = await ctx["api"].post(
        "/api/v1/knowledge/documents",
        files={
            "file": (
                "temperature.md",
                "# 温度\n温度用温度计测量。".encode(),
                "text/markdown",
            )
        },
    )
    assert upload.status_code == 202, upload.text
    document = upload.json()["data"]
    await ctx["worker"].run_once(task_id=document["task_id"])
    revised = await ctx["api"].patch(
        f"/api/v1/qa/sessions/{session['session_id']}/scope",
        json={
            "scope": {"documents": [{"doc_id": document["doc_id"]}]},
            "expected_revision": 1,
        },
    )
    assert revised.status_code == 200, revised.text
    revised = revised.json()["data"]
    deleted = await ctx["api"].delete(
        "/api/v1/knowledge/documents/" + ctx["document"]["doc_id"]
    )
    assert deleted.status_code == 202, deleted.text

    locked, release, cleanup_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    connection_ids = {}
    operation = ContextVar("qa_cleanup_operation", default=None)
    original_transaction = qa_service.transaction
    original_owned_session = qa_read.owned_session

    @asynccontextmanager
    async def observed_transaction():
        async with original_transaction() as conn:
            name = operation.get()
            connection_ids[name] = conn.thread_id()
            if name == "qa-cleanup":
                cleanup_started.set()
            yield conn

    async def hold_submission(*args, **kwargs):
        row = await original_owned_session(*args, **kwargs)
        if kwargs.get("lock") and operation.get() == "qa-new-question":
            locked.set()
            await release.wait()
        return row

    monkeypatch.setattr(qa_service, "transaction", observed_transaction)
    monkeypatch.setattr(qa_read, "owned_session", hold_submission)

    async def new_question():
        operation.set("qa-new-question")
        return await ask(ctx, revised, key="new-range", content="温度怎么测量？")

    async def purge_old_scope():
        operation.set("qa-cleanup")
        return await qa_service.purge_document(
            ctx["actor"].owner_id, ctx["document"]["doc_id"]
        )

    submission = asyncio.create_task(new_question(), name="qa-new-question")
    cleanup = None
    try:
        await asyncio.wait_for(locked.wait(), timeout=10)
        cleanup = asyncio.create_task(
            purge_old_scope(),
            name="qa-cleanup",
        )
        await asyncio.wait_for(cleanup_started.wait(), timeout=10)

        async def wait_until_cleanup_blocks():
            while True:
                if cleanup.done():
                    await cleanup
                    pytest.fail("Cleanup finished despite the locked session")
                waiting = await fetch_one(
                    "SELECT 1 AS waiting FROM performance_schema.data_lock_waits w "
                    "JOIN performance_schema.threads t ON t.THREAD_ID=w.REQUESTING_THREAD_ID "
                    "WHERE t.PROCESSLIST_ID=%s LIMIT 1",
                    (connection_ids["qa-cleanup"],),
                )
                if waiting:
                    return
                await asyncio.sleep(0.025)

        await asyncio.wait_for(wait_until_cleanup_blocks(), timeout=10)
        release.set()
        submitted, _ = await asyncio.wait_for(
            asyncio.gather(submission, cleanup), timeout=10
        )
    finally:
        release.set()
        for pending in (submission, cleanup):
            if pending is not None and not pending.done():
                pending.cancel()
        await asyncio.gather(
            *(task for task in (submission, cleanup) if task), return_exceptions=True
        )

    assert submitted.status_code == 202, submitted.text
    assert submitted.json()["data"]["status"] == "pending"
    persisted = await fetch_one(
        "SELECT a.artifact_json,f.comment,f.evaluation_consent FROM qa_answers a "
        "JOIN qa_feedback f ON f.answer_id=a.answer_id WHERE a.answer_id=%s",
        (answer_id,),
    )
    assert persisted == {"artifact_json": None, "comment": "", "evaluation_consent": 0}
    task = await fetch_one(
        "SELECT request_json FROM quiz_tasks WHERE task_id=%s", (original["task_id"],)
    )
    assert "question" not in load(task["request_json"])
    messages = (
        await ctx["api"].get(f"/api/v1/qa/sessions/{session['session_id']}/messages")
    ).json()["data"]["items"]
    assert [message["status"] for message in messages[:2]] == ["revoked", "revoked"]
    assert messages[2]["content"] == "温度怎么测量？"

    # Repeating the durable cleanup and executing the new question remain safe.
    await ctx["worker"].run_once(task_id=deleted.json()["data"]["task_id"])
    deleted_job = await fetch_one(
        "SELECT status FROM quiz_tasks WHERE task_id=%s",
        (deleted.json()["data"]["task_id"],),
    )
    assert deleted_job["status"] == "completed"
    task_id = submitted.json()["data"]["task_id"]
    await ctx["worker"].run_once(task_id=task_id)
    finished = (await ctx["api"].get(f"/api/v1/qa/tasks/{task_id}")).json()["data"]
    assert finished["status"] == "completed", finished
