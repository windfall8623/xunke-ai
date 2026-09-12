"""Document selection is normalized, authorized, and persisted before dispatch."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.errors import AppError
from app.models.learning import GenerateBody
from app.rag.contracts import ActorContext, ResolvedScope, SourceManifest
from app.rag.errors import InvalidScope
from app.services import quiz_service
from tests.test_api import api_request


@pytest.fixture
def generation_actor():
    return ActorContext(owner_id=1, roles=["learner"])


@pytest.fixture
def resolved_document_scope():
    return ResolvedScope(owner_id=1, namespace="production", documents=[
        SourceManifest(owner_id=1, namespace="production", doc_id="doc_1",
                       document_version_id="version_1", source_sha256="a" * 64,
                       parse_artifact_id="parse_1", canonical_text_hash="b" * 64,
                       index_build_id="build_1", attempt_id="attempt_1", authorization_revision=2),
    ])


@pytest.fixture
def durable_job():
    existing = AsyncMock(return_value=None)
    enqueue = AsyncMock(return_value={"task_id": "task_1"})
    view = AsyncMock(return_value={"task_id": "task_1", "status": "pending", "stage": "queued"})
    with (
        patch("app.services.job_service.existing_job", existing),
        patch("app.services.job_service.enqueue_job", enqueue),
        patch("app.services.job_service.get_task", view),
    ):
        yield SimpleNamespace(existing=existing, enqueue=enqueue, view=view)


@pytest.mark.asyncio
class TestQuizJobSourceScope:
    async def test_no_document_saves_topic_mode_without_private_retrieval(self, generation_actor, durable_job):
        with patch("app.services.source_service.resolve_scope", AsyncMock()) as resolve:
            task = await quiz_service.create_quiz_job(
                generation_actor, GenerateBody(user_input="学习 Python", question_count=3), "topic-1")
        assert task["status"] == "pending"
        request = durable_job.enqueue.await_args.args[2]
        assert request["source_policy"] == "topic"
        assert request["scope"] is None
        assert durable_job.enqueue.await_args.kwargs["scope"] is None
        resolve.assert_not_awaited()

    async def test_legacy_doc_id_persists_strict_versioned_scope(
        self, generation_actor, resolved_document_scope, durable_job
    ):
        with patch("app.services.source_service.resolve_scope", AsyncMock(return_value=resolved_document_scope)) as resolve:
            task = await quiz_service.create_quiz_job(
                generation_actor, GenerateBody(user_input="学习 Python", doc_id="doc_1", question_count=3), "document-1")
        assert task["task_id"] == "task_1"
        request = durable_job.enqueue.await_args.args[2]
        assert request["source_policy"] == "strict_docs"
        assert "doc_id" not in request
        assert request["scope"]["documents"][0]["doc_id"] == "doc_1"
        assert durable_job.enqueue.await_args.kwargs["scope"] == resolved_document_scope.model_dump(mode="json")
        assert resolve.await_args.args[0] == generation_actor
        assert resolve.await_args.args[1].documents[0].doc_id == "doc_1"

    async def test_doc_id_without_login_rejected_before_dispatch(self, durable_job):
        response = await api_request("POST", "/api/v1/quiz/generate/async",
            headers={"Idempotency-Key": "guest-doc"},
            json={"user_input": "学习 Python", "doc_id": "doc_1"})
        assert response.status_code == 401
        durable_job.enqueue.assert_not_awaited()

    @pytest.mark.parametrize("status,code", [(404, "not_found"), (409, "document_not_ready")])
    async def test_unavailable_document_is_rejected_before_task_creation(
        self, generation_actor, durable_job, status, code
    ):
        with patch("app.services.source_service.resolve_scope",
                   AsyncMock(side_effect=AppError(status, code, "资料不可用"))):
            with pytest.raises(AppError) as error:
                await quiz_service.create_quiz_job(
                    generation_actor, GenerateBody(user_input="学习 Python", doc_id="doc_1"), "unavailable")
        assert error.value.status == status and error.value.code == code
        durable_job.enqueue.assert_not_awaited()

    async def test_idempotent_retry_does_not_resolve_new_active_version(self, generation_actor, durable_job):
        durable_job.existing.return_value = {"task_id": "original-task"}
        with patch("app.services.source_service.resolve_scope", AsyncMock()) as resolve:
            await quiz_service.create_quiz_job(
                generation_actor, GenerateBody(user_input="学习 Python", doc_id="doc_1"), "same-intent")
        durable_job.view.assert_awaited_once_with(1, "original-task")
        durable_job.enqueue.assert_not_awaited()
        resolve.assert_not_awaited()

    @pytest.mark.parametrize("selection", [
        {"doc_id": "doc_1", "scope": {"documents": [{"doc_id": "doc_1"}]}},
        {"doc_id": "doc_1", "source_policy": "topic"},
    ])
    async def test_ambiguous_scope_cannot_enqueue(self, generation_actor, durable_job, selection):
        with pytest.raises(InvalidScope):
            await quiz_service.create_quiz_job(
                generation_actor, GenerateBody(user_input="学习 Python", **selection), "ambiguous")
        durable_job.enqueue.assert_not_awaited()

    async def test_selected_sections_keep_the_catalog_revision(
        self, generation_actor, resolved_document_scope, durable_job
    ):
        body = GenerateBody(user_input="学习本节", source_policy="strict_docs", scope={"documents": [{
            "doc_id": "doc_1", "section_ids": ["parse_1:section_1"], "section_catalog_revision": "parse_1",
        }]})
        with patch("app.services.source_service.resolve_scope", AsyncMock(return_value=resolved_document_scope)) as resolve:
            await quiz_service.create_quiz_job(generation_actor, body, "section-1")
        selected = resolve.await_args.args[1].documents[0]
        assert selected.section_ids == ["parse_1:section_1"]
        assert selected.section_catalog_revision == "parse_1"
        assert durable_job.enqueue.await_args.args[2]["scope"] == body.scope.model_dump(mode="json")
