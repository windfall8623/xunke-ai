"""Real HTTP/MySQL tests for QA ordering, isolation, version pins and revocation."""

import asyncio
import uuid

import httpx
from tests.platform.conftest import register_email_account
import pytest

from tests.platform.qa_helpers import ask, new_session
from tests.platform.qa_helpers import qa_context as qa_context


@pytest.mark.asyncio
async def test_qa_session_is_pinned_and_private(qa_context):
    ctx = qa_context
    session = await new_session(ctx)
    assert session["scope_revision"] == 1
    assert (
        session["scope"]["documents"][0]["document_version_id"]
        == ctx["document"]["active_version_id"]
    )
    assert session["active_task_id"] is None
    listing = await ctx["api"].get("/api/v1/qa/sessions")
    assert listing.json()["data"]["total"] == 1
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as other:
        reg_session, _ = await register_email_account(other, nickname="另一用户")
        other.headers.update(
            {
                "Origin": "http://testserver",
                "X-CSRF-Token": reg_session["csrf_token"],
            }
        )
        assert (
            await other.get(f"/api/v1/qa/sessions/{session['session_id']}")
        ).status_code == 404
        assert (
            await other.get(f"/api/v1/qa/sessions/{session['session_id']}/messages")
        ).status_code == 404
        assert (
            await other.post(
                "/api/v1/qa/sessions",
                json={"scope": {"documents": [{"doc_id": ctx["document"]["doc_id"]}]}},
            )
        ).status_code == 404
        assert (await other.get("/api/v1/qa/sessions")).json()["data"]["total"] == 0


@pytest.mark.asyncio
async def test_qa_submit_is_durable_idempotent_and_serial(qa_context):
    from app.core.db import fetch_one

    ctx = qa_context
    session = await new_session(ctx)
    first, replay = await asyncio.gather(ask(ctx, session), ask(ctx, session))
    assert first.status_code == replay.status_code == 202, (first.text, replay.text)
    task = first.json()["data"]
    assert replay.json()["data"]["task_id"] == task["task_id"]
    assert task["status"] == "pending" and task["answer"] is None
    assert (await ask(ctx, session, content="不同的问题")).status_code == 409
    assert (await ask(ctx, session, key="second-while-busy")).status_code == 409
    rows = await fetch_one(
        "SELECT COUNT(*) AS n FROM qa_messages WHERE session_id=%s",
        (session["session_id"],),
    )
    assert rows["n"] == 2
    listing = (
        await ctx["api"].get(f"/api/v1/qa/sessions/{session['session_id']}/messages")
    ).json()["data"]
    assert [item["role"] for item in listing["items"]] == ["user", "assistant"]
    assert [item["sequence"] for item in listing["items"]] == [1, 2]
    assert listing["items"][1]["status"] == "pending"


@pytest.mark.asyncio
async def test_qa_same_key_cannot_cross_sessions(qa_context):
    first = await new_session(qa_context)
    second = await new_session(qa_context)
    assert (await ask(qa_context, first)).status_code == 202
    assert (await ask(qa_context, second)).status_code == 409


@pytest.mark.asyncio
async def test_qa_scope_revision_and_cancel_are_consistent(qa_context):
    ctx = qa_context
    session = await new_session(ctx)
    path = f"/api/v1/qa/sessions/{session['session_id']}/scope"
    body = {
        "scope": {"documents": [{"doc_id": ctx["document"]["doc_id"]}]},
        "expected_revision": 1,
    }
    task = (await ask(ctx, session)).json()["data"]
    assert (await ctx["api"].patch(path, json=body)).status_code == 409
    cancelled = await ctx["api"].post(f"/api/v1/qa/tasks/{task['task_id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["data"]["status"] == "cancelled"
    revised = await ctx["api"].patch(path, json=body)
    assert revised.status_code == 200, revised.text
    assert revised.json()["data"]["scope_revision"] == 2
    assert (await ctx["api"].patch(path, json=body)).status_code == 409
    replay = await ask(ctx, session)
    assert replay.status_code == 202 and replay.json()["data"]["status"] == "cancelled"
    assert (await ask(ctx, session, key="stale-revision")).status_code == 409
    assert (
        await ask(ctx, revised.json()["data"], key="new-revision")
    ).status_code == 202


@pytest.mark.asyncio
async def test_qa_history_cursor_does_not_duplicate_messages(qa_context):
    ctx = qa_context
    session = await new_session(ctx)
    for index in range(3):
        task = (await ask(ctx, session, key=f"message-{index}")).json()["data"]
        await ctx["api"].post(f"/api/v1/qa/tasks/{task['task_id']}/cancel")
    path = f"/api/v1/qa/sessions/{session['session_id']}/messages"
    latest = (await ctx["api"].get(path + "?page_size=2")).json()["data"]
    assert [item["sequence"] for item in latest["items"]] == [5, 6]
    assert latest["has_more"] is True
    previous = (
        await ctx["api"].get(
            path + f"?page_size=2&before_sequence={latest['next_before']}"
        )
    ).json()["data"]
    assert [item["sequence"] for item in previous["items"]] == [3, 4]


@pytest.mark.asyncio
async def test_qa_revocation_masks_user_text_history_and_scope(qa_context):
    ctx = qa_context
    session = await new_session(ctx, title="私有资料相关标题")
    task = (await ask(ctx, session, content="用户问题引用的秘密片段")).json()["data"]
    deleted = await ctx["api"].delete(
        "/api/v1/knowledge/documents/" + ctx["document"]["doc_id"]
    )
    assert deleted.status_code == 202
    view = (
        await ctx["api"].get(f"/api/v1/qa/sessions/{session['session_id']}")
    ).json()["data"]
    assert view["source_status"] == "revoked" and view["scope"] is None
    assert "私有" not in view["title"]
    history = await ctx["api"].get(
        f"/api/v1/qa/sessions/{session['session_id']}/messages"
    )
    assert history.status_code == 200
    assert "秘密片段" not in history.text
    assert all(
        item["status"] == "revoked" and item["answer"] is None
        for item in history.json()["data"]["items"]
    )
    assert (
        await ctx["api"].get(f"/api/v1/qa/tasks/{task['task_id']}")
    ).status_code == 404
    assert (await ask(ctx, session, key="revoked-new")).status_code == 404


@pytest.mark.asyncio
async def test_qa_mutations_require_csrf(qa_context):
    api = qa_context["api"]
    csrf = api.headers.pop("X-CSRF-Token")
    try:
        response = await api.post(
            "/api/v1/qa/sessions",
            json={
                "scope": {"documents": [{"doc_id": qa_context["document"]["doc_id"]}]}
            },
        )
        assert response.status_code == 403
    finally:
        api.headers["X-CSRF-Token"] = csrf


@pytest.mark.asyncio
async def test_qa_rejects_unready_source_and_empty_scope(qa_context):
    api = qa_context["api"]
    assert (
        await api.post("/api/v1/qa/sessions", json={"scope": {"documents": []}})
    ).status_code == 422
    pending = await api.post(
        "/api/v1/knowledge/documents",
        files={"file": ("pending.txt", b"synthetic source", "text/plain")},
    )
    assert pending.status_code == 202
    response = await api.post(
        "/api/v1/qa/sessions",
        json={"scope": {"documents": [{"doc_id": pending.json()["data"]["doc_id"]}]}},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_qa_scope_change_cannot_restore_a_title_from_revoked_sources(qa_context):
    ctx = qa_context
    session = await new_session(ctx, title="旧资料的机密标题")
    upload = await ctx["api"].post(
        "/api/v1/knowledge/documents",
        files={
            "file": (
                "new-scope.md",
                "# 新资料\n温度用温度计测量。".encode(),
                "text/markdown",
            )
        },
    )
    document = upload.json()["data"]
    await ctx["worker"].run_once(task_id=document["task_id"])
    changed = await ctx["api"].patch(
        f"/api/v1/qa/sessions/{session['session_id']}/scope",
        json={
            "scope": {"documents": [{"doc_id": document["doc_id"]}]},
            "expected_revision": 1,
        },
    )
    assert changed.status_code == 200, changed.text
    deleted = await ctx["api"].delete(
        "/api/v1/knowledge/documents/" + ctx["document"]["doc_id"]
    )
    assert deleted.status_code == 202
    for path in (f"/api/v1/qa/sessions/{session['session_id']}", "/api/v1/qa/sessions"):
        view = await ctx["api"].get(path)
        assert view.status_code == 200
        assert "机密标题" not in view.text
    assert changed.json()["data"]["source_status"] == "active"
