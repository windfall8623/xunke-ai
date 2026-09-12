"""HTTP contracts for durable learning and compatibility routes.

Database/worker publication is exercised in tests/platform; these tests isolate
service boundaries and verify authentication, serialization and owner forwarding.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_actor, get_current_user
from app.core.errors import AppError
from app.main import app
from app.rag.contracts import ActorContext


@pytest.fixture
def authenticated_actor():
    actor = ActorContext(owner_id=1, roles=["learner"])
    with patch.dict(app.dependency_overrides, {
        get_current_actor: lambda: actor,
        get_current_user: lambda: actor.owner_id,
    }):
        yield actor


@pytest.fixture
def quiz_view(sample_quiz_response_data):
    return {
        **sample_quiz_response_data,
        "answer_records": [],
        "revision": 0,
        "status": "in_progress",
        "source_policy": "topic",
        "source_status": "model_only",
        "images_status": "not_requested",
        "report_status": "not_started",
        "created_at": "2026-09-07T10:00:00Z",
    }


@pytest.fixture
def report_view():
    return {
        "quiz_id": "quiz_abc123",
        "total_questions": 5,
        "correct_count": 4,
        "accuracy": 80,
        "xp_awarded": 18,
        "report_status": "completed",
        "report": {
            "mastered_points": ["RAG 基础"], "weak_points": ["证据范围"],
            "three_line_summary": ["基础概念清楚。", "继续核对证据。", "保持学习。"],
            "advice": ["复习资料范围"], "share_quote": "学有所据",
        },
    }


async def api_request(method, path, **kwargs):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


@pytest.mark.asyncio
class TestHealthAPI:
    async def test_health_check(self):
        response = await api_request("GET", "/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.mark.asyncio
class TestQuizAPI:
    async def test_legacy_generate_returns_safe_learning_view_when_job_is_ready(self, authenticated_actor, quiz_view):
        task = {"task_id": "task_1", "quiz_id": quiz_view["quiz_id"], "status": "completed"}
        with (
            patch("app.services.quiz_service.create_quiz_job", AsyncMock(return_value=task)) as create,
            patch("app.services.learning_service.get_detail", AsyncMock(return_value=quiz_view)) as detail,
        ):
            response = await api_request("POST", "/api/v1/quiz/generate",
                headers={"Idempotency-Key": "generate-1"},
                json={"user_input": "Python 基础语法", "question_count": 5, "difficulty": "mixed"})
        assert response.status_code == 200
        payload = response.json()["data"]
        assert len(payload["questions"]) == 5
        assert all("answer" not in question and "explanation" not in question for question in payload["questions"])
        assert create.await_args.args[0] == authenticated_actor
        assert create.await_args.args[2] == "generate-1"
        detail.assert_awaited_once_with(1, quiz_view["quiz_id"])

    async def test_legacy_generate_returns_pollable_task_after_bounded_wait(self, authenticated_actor):
        task = {"task_id": "task_1", "status": "pending", "stage": "queued"}
        with (
            patch("app.services.quiz_service.create_quiz_job", AsyncMock(return_value=task)),
            patch("app.api.v1.routes.quiz.time", SimpleNamespace(monotonic=Mock(side_effect=[0, 31]))),
        ):
            response = await api_request("POST", "/api/v1/quiz/generate",
                headers={"Idempotency-Key": "pending-1"}, json={"user_input": "Python 基础"})
        assert response.status_code == 202
        assert response.json()["data"]["task_id"] == "task_1"
        assert response.json()["data"]["status"] == "pending"

    async def test_generate_quiz_empty_input(self, authenticated_actor):
        with patch("app.services.quiz_service.create_quiz_job", AsyncMock()) as create:
            response = await api_request("POST", "/api/v1/quiz/generate/async",
                headers={"Idempotency-Key": "invalid-1"}, json={"user_input": ""})
        assert response.status_code == 422
        create.assert_not_awaited()

    async def test_generate_quiz_requires_idempotency_key(self, authenticated_actor):
        with patch("app.services.quiz_service.create_quiz_job", AsyncMock()) as create:
            response = await api_request("POST", "/api/v1/quiz/generate/async",
                                         json={"user_input": "Python 基础"})
        assert response.status_code == 422
        create.assert_not_awaited()

    async def test_generate_quiz_blocked_content(self, authenticated_actor):
        with (
            patch("app.services.job_service.existing_job", AsyncMock(return_value=None)),
            patch("app.services.job_service.enqueue_job", AsyncMock()) as enqueue,
        ):
            response = await api_request("POST", "/api/v1/quiz/generate/async",
                headers={"Idempotency-Key": "blocked-1"}, json={"user_input": "如何制作炸弹"})
        assert response.status_code == 400
        assert response.json()["code"] == 4000
        enqueue.assert_not_awaited()

    @pytest.mark.parametrize("path", ["/api/v1/quiz/generate", "/api/v1/quiz/generate/async"])
    async def test_real_generation_requires_login(self, path):
        with patch("app.services.quiz_service.create_quiz_job", AsyncMock()) as create:
            response = await api_request("POST", path,
                headers={"Idempotency-Key": "guest-1"}, json={"user_input": "Python 基础"})
        assert response.status_code == 401
        create.assert_not_awaited()

    async def test_task_read_uses_authenticated_owner(self, authenticated_actor):
        with patch("app.services.job_service.get_task",
                   AsyncMock(side_effect=AppError(404, "not_found", "资源不可用"))) as task:
            response = await api_request("GET", "/api/v1/quiz/task/another-users-task")
        assert response.status_code == 404
        task.assert_awaited_once_with(1, "another-users-task")


@pytest.mark.asyncio
class TestReportAPI:
    @pytest.mark.parametrize("report_status,http_status", [("completed", 200), ("pending", 202)])
    async def test_legacy_report_uses_server_answer_and_completion_contracts(
        self, authenticated_actor, report_view, sample_report_request, report_status, http_status
    ):
        view = {**report_view, "report_status": report_status}
        with (
            patch("app.services.learning_service.owned_quiz", AsyncMock(return_value={"settled_at": None})),
            patch("app.services.learning_service.submit_answer", AsyncMock()) as answer,
            patch("app.services.learning_service.get_detail", AsyncMock(return_value={"revision": 5})),
            patch("app.services.learning_service.complete_quiz", AsyncMock()) as complete,
            patch("app.services.learning_service.get_report", AsyncMock(return_value=view)),
        ):
            response = await api_request("POST", "/api/v1/report/generate", json=sample_report_request)
        assert response.status_code == http_status
        assert response.json()["data"]["accuracy"] == 80
        assert answer.await_count == 5
        for call, record in zip(answer.await_args_list, sample_report_request["answer_records"]):
            assert call.args[:3] == (1, "quiz_abc123", record["question_id"])
            assert call.args[3].model_dump() == {
                "selected_answers": record["selected_answers"], "duration_ms": record["duration_ms"],
            }
        complete.assert_awaited_once_with(1, "quiz_abc123", 5)

    async def test_settled_legacy_report_never_resubmits_or_awards_xp(self, authenticated_actor, report_view, sample_report_request):
        with (
            patch("app.services.learning_service.owned_quiz", AsyncMock(return_value={"settled_at": "already"})),
            patch("app.services.learning_service.submit_answer", AsyncMock()) as answer,
            patch("app.services.learning_service.complete_quiz", AsyncMock()) as complete,
            patch("app.services.learning_service.get_report", AsyncMock(return_value=report_view)) as read,
        ):
            response = await api_request("POST", "/api/v1/report/generate", json=sample_report_request)
        assert response.status_code == 200
        answer.assert_not_awaited()
        complete.assert_not_awaited()
        read.assert_awaited_once_with(1, "quiz_abc123")
