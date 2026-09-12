"""Authenticated user, history and compatibility HTTP contracts."""
from unittest.mock import AsyncMock, patch

import pytest

from app.core.errors import AppError
from app.core.exceptions import AuthenticationError
from app.models.user import LoginResponse, UserBrief
from tests.test_api import api_request, authenticated_actor, quiz_view, report_view  # noqa: F401 - pytest fixture registration


@pytest.mark.asyncio
class TestLoginAPI:
    @pytest.mark.parametrize("user_id,nickname,xp", [(1, "学习者", 0), (5, "已有学习者", 100)])
    async def test_wechat_login_returns_service_identity_without_resetting_xp(self, user_id, nickname, xp):
        result = LoginResponse(token="synthetic-token", user=UserBrief(
            id=user_id, nickname=nickname, avatar_url="", total_xp=xp))
        with (
            patch("app.services.auth_service.rate_limit", AsyncMock()) as rate,
            patch("app.services.user_service.handle_login", AsyncMock(return_value=result)) as login,
        ):
            response = await api_request("POST", "/api/v1/user/login", json={"code": "synthetic-wx-code"})
        assert response.status_code == 200
        assert response.json()["data"]["user"] == result.user.model_dump()
        assert response.json()["data"]["token"] == "synthetic-token"
        login.assert_awaited_once_with("synthetic-wx-code")
        assert rate.await_args.args[:2] == ("wechat_login", "synthetic-wx-code")

    async def test_login_empty_code_rejected(self):
        with patch("app.services.user_service.handle_login", AsyncMock()) as login:
            response = await api_request("POST", "/api/v1/user/login", json={"code": ""})
        assert response.status_code == 422
        login.assert_not_awaited()

    async def test_rate_limit_stops_identity_lookup(self):
        with (
            patch("app.services.auth_service.rate_limit",
                  AsyncMock(side_effect=AppError(429, "rate_limited", "请稍后再试"))),
            patch("app.services.user_service.handle_login", AsyncMock()) as login,
        ):
            response = await api_request("POST", "/api/v1/user/login", json={"code": "rate-limited"})
        assert response.status_code == 429
        login.assert_not_awaited()

    async def test_invalid_wechat_credentials_remain_unauthorized(self):
        with (
            patch("app.services.auth_service.rate_limit", AsyncMock()),
            patch("app.services.user_service.handle_login",
                  AsyncMock(side_effect=AuthenticationError("微信登录失败"))),
        ):
            response = await api_request("POST", "/api/v1/user/login", json={"code": "invalid"})
        assert response.status_code == 401


@pytest.mark.asyncio
class TestProfileAPI:
    async def test_get_profile_success(self, authenticated_actor):
        with (
            patch("app.services.user_service.user_repository.get_user_by_id",
                  AsyncMock(return_value={"id": 1, "nickname": "测试学习者", "avatar_url": "", "total_xp": 18})) as user,
            patch("app.services.user_service.quiz_repository.get_user_quiz_count", AsyncMock(return_value=3)),
            patch("app.services.user_service.quiz_repository.get_user_answer_stats",
                  AsyncMock(return_value={"correct_count": 12, "average_accuracy": 80})),
        ):
            response = await api_request("GET", "/api/v1/user/profile")
        assert response.status_code == 200
        assert response.json()["data"]["quiz_count"] == 3
        assert response.json()["data"]["correct_count"] == 12
        assert response.json()["data"]["average_accuracy"] == 80
        user.assert_awaited_once_with(1)

    async def test_get_profile_unauthorized(self):
        response = await api_request("GET", "/api/v1/user/profile")
        assert response.status_code == 401

    async def test_update_profile_success(self, authenticated_actor):
        with patch("app.services.user_service.user_repository.update_user_profile", AsyncMock()) as update:
            response = await api_request("PUT", "/api/v1/user/profile", json={"nickname": "新昵称"})
        assert response.status_code == 200
        assert response.json()["data"] is None
        update.assert_awaited_once_with(1, "新昵称", None)

    async def test_arbitrary_avatar_url_cannot_be_saved(self, authenticated_actor):
        with patch("app.services.user_service.update_profile", AsyncMock()) as update:
            response = await api_request("PUT", "/api/v1/user/profile",
                                         json={"avatar_url": "https://example.org/unowned.png"})
        assert response.status_code == 422
        assert response.json()["error_code"] == "invalid_avatar"
        update.assert_not_awaited()

    async def test_upload_avatar_forwards_authenticated_owner(self, authenticated_actor):
        with patch("app.services.asset_service.save_avatar",
                   AsyncMock(return_value={"avatar_url": "/api/v1/user/assets/asset_1"})) as save:
            response = await api_request("POST", "/api/v1/user/avatar",
                files={"file": ("avatar.png", b"synthetic-service-fixture", "image/png")})
        assert response.status_code == 201
        assert response.json()["data"]["avatar_url"] == "/api/v1/user/assets/asset_1"
        assert save.await_args.args[0] == 1
        assert save.await_args.args[1].filename == "avatar.png"


@pytest.mark.asyncio
class TestQuizHistoryAPI:
    async def test_get_quiz_list(self, authenticated_actor):
        item = {
            "quiz_id": "quiz_abc123", "title": "RAG 入门", "accuracy": 80,
            "question_count": 5, "answered_count": 5, "revision": 5, "status": "settled",
            "source_status": "grounded", "images_status": "not_requested",
            "report_status": "pending", "created_at": "2026-09-07T10:00:00Z",
        }
        with patch("app.services.learning_service.history",
                   AsyncMock(return_value={"items": [item], "total": 11, "page": 2, "page_size": 10})) as history:
            response = await api_request("GET", "/api/v1/user/quizzes?page=2&page_size=10")
        assert response.status_code == 200
        assert response.json()["data"]["items"][0]["report_status"] == "pending"
        assert response.json()["data"]["total"] == 11
        history.assert_awaited_once_with(1, 2, 10)

    async def test_get_quiz_list_unauthorized(self):
        response = await api_request("GET", "/api/v1/user/quizzes")
        assert response.status_code == 401

    async def test_history_page_size_is_bounded(self, authenticated_actor):
        with patch("app.services.learning_service.history", AsyncMock()) as history:
            response = await api_request("GET", "/api/v1/user/quizzes?page_size=51")
        assert response.status_code == 422
        history.assert_not_awaited()

    async def test_get_quiz_detail_does_not_expose_unanswered_solutions(self, authenticated_actor, quiz_view):
        with patch("app.services.learning_service.get_detail", AsyncMock(return_value=quiz_view)) as detail:
            response = await api_request("GET", "/api/v1/user/quizzes/quiz_abc123")
        assert response.status_code == 200
        assert response.json()["data"]["quiz_id"] == "quiz_abc123"
        assert all("answer" not in question for question in response.json()["data"]["questions"])
        detail.assert_awaited_once_with(1, "quiz_abc123")

    async def test_get_quiz_detail_not_found(self, authenticated_actor):
        with patch("app.services.learning_service.get_detail",
                   AsyncMock(side_effect=AppError(404, "not_found", "资源不可用"))):
            response = await api_request("GET", "/api/v1/user/quizzes/foreign-or-missing")
        assert response.status_code == 404
        assert response.json()["data"] is None


@pytest.mark.asyncio
class TestLearningWithRequiredAuth:
    async def test_quiz_generate_without_token_is_rejected(self):
        with patch("app.services.quiz_service.create_quiz_job", AsyncMock()) as create:
            response = await api_request("POST", "/api/v1/quiz/generate/async",
                headers={"Idempotency-Key": "guest"}, json={"user_input": "Python 基础", "question_count": 3})
        assert response.status_code == 401
        create.assert_not_awaited()

    async def test_authenticated_quiz_request_creates_durable_task(self, authenticated_actor):
        with patch("app.services.quiz_service.create_quiz_job",
                   AsyncMock(return_value={"task_id": "task_1", "status": "pending"})) as create:
            response = await api_request("POST", "/api/v1/quiz/generate/async",
                headers={"Idempotency-Key": "authenticated"}, json={"user_input": "Python 基础", "question_count": 3})
        assert response.status_code == 202
        assert response.json()["data"]["task_id"] == "task_1"
        assert create.await_args.args[0] == authenticated_actor
        assert create.await_args.args[1].question_count == 3
        assert create.await_args.args[2] == "authenticated"

    async def test_report_generation_requires_identity(self, sample_report_request):
        with patch("app.services.learning_service.owned_quiz", AsyncMock()) as owned:
            response = await api_request("POST", "/api/v1/report/generate", json=sample_report_request)
        assert response.status_code == 401
        owned.assert_not_awaited()

    async def test_report_failure_keeps_confirmed_statistics_without_settlement(self, authenticated_actor, report_view):
        with (
            patch("app.services.learning_service.get_report",
                  AsyncMock(return_value={**report_view, "report_status": "failed", "report": None})),
            patch("app.services.learning_service.complete_quiz", AsyncMock()) as complete,
        ):
            response = await api_request("GET", "/api/v1/report/quiz_abc123")
        assert response.status_code == 200
        assert response.json()["data"]["accuracy"] == 80
        assert response.json()["data"]["xp_awarded"] == 18
        complete.assert_not_awaited()

    async def test_report_retry_forwards_owner_and_idempotency_key(self, authenticated_actor):
        with patch("app.services.learning_service.retry_report",
                   AsyncMock(return_value={"quiz_id": "quiz_abc123", "report_status": "pending"})) as retry:
            response = await api_request("POST", "/api/v1/report/quiz_abc123/retry",
                                         headers={"Idempotency-Key": "report-retry-1"})
        assert response.status_code == 202
        assert response.json()["data"] == {"quiz_id": "quiz_abc123", "report_status": "pending"}
        retry.assert_awaited_once_with(1, "quiz_abc123", "report-retry-1")
