from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_anonymous_auth_capabilities_expose_only_the_configured_flag(
    monkeypatch, enabled
):
    from app.api.v1.routes import auth

    monkeypatch.setattr(
        auth,
        "get_settings",
        lambda: SimpleNamespace(
            legacy_link_enabled=enabled,
            wechat_app_secret="must-not-be-returned",
            jwt_secret="must-not-be-returned-either",
            email_registration_enabled=False,
            email_code_secret="",
            email_send_cooldown_seconds=60,
            email_send_max_per_email_per_day=5,
            email_send_max_per_ip_per_hour=10,
            email_send_daily_limit=100,
            smtp_security="ssl",
            smtp_host="",
            smtp_username="",
            smtp_password="",
            smtp_from_email="",
            smtp_from_name="循课",
        ),
    )
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/v1/auth/capabilities")
    assert response.status_code == 200
    assert response.json()["data"] == {
        "legacy_link_enabled": enabled,
        "email_registration_enabled": False,
        "email_verification_required": True,
        "email_code_cooldown_seconds": 60,
    }
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert "must-not-be-returned" not in response.text


def permission_app(actor):
    from fastapi.responses import JSONResponse

    from app.api.v1.routes import evaluation, feedback, knowledge
    from app.core.auth import get_current_actor
    from app.core.errors import AppError

    app = FastAPI()
    for router in (
        evaluation.router, feedback.router, knowledge.router, knowledge.eval_router
    ):
        app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_current_actor] = lambda: actor

    @app.exception_handler(AppError)
    async def error_handler(request, exc):
        return JSONResponse({"error_code": exc.code}, status_code=exc.status)

    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["learner", "evaluator", "admin"])
@pytest.mark.parametrize("operation", ["create", "resume", "upload", "reindex", "promote"])
async def test_system_evaluation_routes_require_current_admin(monkeypatch, role, operation):
    from unittest.mock import AsyncMock

    from app.api.v1.routes import evaluation, feedback, knowledge
    from app.core import db
    from app.core.errors import AppError
    from app.rag.contracts import ActorContext

    actor = ActorContext(owner_id=7, role=role)
    cases = {
        "create": (evaluation.runs, "create_run", "/eval/runs", {"json": {
            "dataset_id": "dataset", "dataset_version": 1, "pipeline_id": "dense-v1",
            "max_cost_cny": 2,
        }, "headers": {"Idempotency-Key": "key"}}),
        "resume": (evaluation.runs, "resume_run", "/eval/runs/run/resume", {}),
        "upload": (knowledge.service, "upload_document", "/eval/documents", {
            "files": {"file": ("fixture.txt", b"synthetic source", "text/plain")},
        }),
        "reindex": (knowledge.service, "reindex_document", "/eval/documents/doc/reindex", {
            "json": {"index_profile_id": "legacy-char-v1"},
        }),
        "promote": (feedback.service, "promote_feedback", "/eval/feedback/feedback/promote", {
            "json": {"expected_revision": 0, "name": "candidate", "redacted_request": "facts"},
        }),
    }
    module, name, path, options = cases[operation]
    dispatch = AsyncMock(side_effect=AppError(409, "fixture_dispatch", "Fixture boundary"))
    monkeypatch.setattr(module, name, dispatch)
    persisted = AsyncMock(return_value={"role": role})
    monkeypatch.setattr(db, "fetch_one", persisted)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=permission_app(actor)), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/v1" + path, **options)
    if role == "admin":
        assert response.status_code == 409, response.text
        assert response.json()["error_code"] == "fixture_dispatch"
        dispatch.assert_awaited_once()
        assert dispatch.await_args.args[0] == (actor.owner_id if operation == "resume" else actor)
    else:
        assert response.status_code == 403, response.text
        assert response.json()["error_code"] == "system_model_admin_required"
        dispatch.assert_not_awaited()
    persisted.assert_awaited_once_with("SELECT role FROM users WHERE id=%s", (7,), conn=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["learner", "evaluator", "admin"])
@pytest.mark.parametrize("operation", ["datasets", "runs", "cancel", "export", "review", "documents", "feedback"])
async def test_nonbillable_workbench_routes_keep_owned_evaluator_access(monkeypatch, role, operation):
    from unittest.mock import AsyncMock

    from app.api.v1.routes import evaluation, feedback, knowledge
    from app.core import db
    from app.core.errors import AppError
    from app.rag.contracts import ActorContext

    actor = ActorContext(owner_id=7, role=role)
    cases = {
        "datasets": (evaluation.datasets, "list_datasets", "GET", "/eval/datasets", {}),
        "runs": (evaluation.runs, "list_runs", "GET", "/eval/runs", {}),
        "cancel": (evaluation.runs, "cancel_run", "POST", "/eval/runs/run/cancel", {}),
        "export": (evaluation.runs, "export_run", "GET", "/eval/runs/run/export", {}),
        "review": (evaluation.runs, "review_result", "PUT", "/eval/runs/run/results/result/review", {
            "json": {"expected_revision": 0, "verdict": "pass"},
        }),
        "documents": (knowledge.service, "list_documents", "GET", "/eval/documents", {}),
        "feedback": (feedback.service, "list_feedback", "GET", "/eval/feedback", {}),
    }
    module, name, method, path, options = cases[operation]
    dispatch = AsyncMock(side_effect=AppError(409, "fixture_dispatch", "Fixture boundary"))
    monkeypatch.setattr(module, name, dispatch)
    persisted = AsyncMock(side_effect=AssertionError("Metadata must not require a system model"))
    monkeypatch.setattr(db, "fetch_one", persisted)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=permission_app(actor)), base_url="http://testserver"
    ) as client:
        response = await client.request(method, "/api/v1" + path, **options)
    if role in {"evaluator", "admin"}:
        assert response.status_code == 409, response.text
        assert response.json()["error_code"] == "fixture_dispatch"
        dispatch.assert_awaited_once()
        assert dispatch.await_args.args[0] == (actor if operation == "review" else actor.owner_id)
    else:
        assert response.status_code == 403, response.text
        assert response.json()["error_code"] == "evaluator_required"
        dispatch.assert_not_awaited()
    persisted.assert_not_awaited()
