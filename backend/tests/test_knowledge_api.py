"""HTTP contracts for owned document versions and deferred indexing."""
from unittest.mock import AsyncMock, patch

import pytest

from app.core.errors import AppError
from tests.test_api import api_request, authenticated_actor  # noqa: F401 - pytest fixture registration


@pytest.fixture
def document_view():
    return {
        "doc_id": "doc_1", "file_name": "a.txt", "file_type": "txt", "file_size": 100,
        "status": "ready", "document_revision": 2, "purpose": "production",
        "active_version_id": "version_1", "active_build_id": "build_1",
        "section_catalog_revision": "parse_1", "chunk_count": 3,
        "sections": [{"section_id": "section_1", "title": "资料章节"}],
    }


@pytest.mark.asyncio
class TestKnowledgeUploadAPI:
    async def test_upload_requires_auth(self):
        with patch("app.services.source_service.upload_document", AsyncMock()) as upload:
            response = await api_request("POST", "/api/v1/knowledge/documents",
                files={"file": ("a.txt", b"hello", "text/plain")})
        assert response.status_code == 401
        upload.assert_not_awaited()

    async def test_upload_accepts_durable_processing(self, authenticated_actor, document_view):
        view = {**document_view, "status": "processing", "task_id": "ingest_1"}
        with patch("app.services.source_service.upload_document", AsyncMock(return_value=view)) as upload:
            response = await api_request("POST", "/api/v1/knowledge/documents",
                files={"file": ("a.txt", b"hello", "text/plain")})
        assert response.status_code == 202
        assert response.json()["data"]["task_id"] == "ingest_1"
        assert response.json()["data"]["status"] == "processing"
        assert upload.await_args.args[0] == authenticated_actor
        assert upload.await_args.args[1].filename == "a.txt"

    async def test_upload_rejects_invalid_document(self, authenticated_actor):
        with patch("app.services.source_service.upload_document",
                   AsyncMock(side_effect=AppError(422, "unsupported_file", "支持 PDF、DOCX、Markdown 和 TXT"))):
            response = await api_request("POST", "/api/v1/knowledge/documents",
                files={"file": ("a.xlsx", b"hello", "application/octet-stream")})
        assert response.status_code == 422
        assert response.json()["error_code"] == "unsupported_file"


@pytest.mark.asyncio
class TestKnowledgeListAPI:
    async def test_list_documents_is_owner_scoped(self, authenticated_actor, document_view):
        with patch("app.services.source_service.list_documents",
                   AsyncMock(return_value={"items": [document_view], "total": 1})) as listing:
            response = await api_request("GET", "/api/v1/knowledge/documents")
        assert response.status_code == 200
        assert response.json()["data"]["items"][0]["doc_id"] == "doc_1"
        listing.assert_awaited_once_with(1)

    async def test_learner_cannot_read_evaluation_sources(self, authenticated_actor):
        with patch("app.services.source_service.list_documents", AsyncMock()) as listing:
            response = await api_request("GET", "/api/v1/eval/documents")
        assert response.status_code == 403
        listing.assert_not_awaited()


@pytest.mark.asyncio
class TestKnowledgeStatusAPI:
    async def test_get_status_success(self, authenticated_actor, document_view):
        row = {"doc_id": "doc_1", "owner_id": 1}
        with (
            patch("app.services.source_service.owned_document", AsyncMock(return_value=row)) as owned,
            patch("app.services.source_service.document_view", AsyncMock(return_value=document_view)) as view,
        ):
            response = await api_request("GET", "/api/v1/knowledge/documents/doc_1")
        assert response.status_code == 200
        assert response.json()["data"]["active_version_id"] == "version_1"
        assert response.json()["data"]["section_catalog_revision"] == "parse_1"
        owned.assert_awaited_once_with(1, "doc_1")
        view.assert_awaited_once_with(row)

    async def test_get_status_not_found(self, authenticated_actor):
        with patch("app.services.source_service.owned_document",
                   AsyncMock(side_effect=AppError(404, "not_found", "资源不可用"))):
            response = await api_request("GET", "/api/v1/knowledge/documents/doc_missing")
        assert response.status_code == 404
        assert response.json()["data"] is None


@pytest.mark.asyncio
class TestKnowledgeVersionAPI:
    async def test_replace_persists_a_new_version(self, authenticated_actor, document_view):
        with patch("app.services.source_service.upload_document",
                   AsyncMock(return_value={**document_view, "status": "processing"})) as upload:
            response = await api_request("POST", "/api/v1/knowledge/documents/doc_1/versions",
                files={"file": ("updated.txt", b"revised", "text/plain")})
        assert response.status_code == 202
        assert upload.await_args.args[0] == authenticated_actor
        assert upload.await_args.kwargs == {"doc_id": "doc_1"}

    async def test_reindex_uses_explicit_allowed_profile(self, authenticated_actor, document_view):
        with patch("app.services.source_service.reindex_document", AsyncMock(return_value=document_view)) as reindex:
            response = await api_request("POST", "/api/v1/knowledge/documents/doc_1/reindex",
                json={"index_profile_id": "structure-v1"})
        assert response.status_code == 202
        reindex.assert_awaited_once_with(authenticated_actor, "doc_1", "structure-v1")

    async def test_reindex_rejects_unlisted_profile(self, authenticated_actor):
        with patch("app.services.source_service.reindex_document", AsyncMock()) as reindex:
            response = await api_request("POST", "/api/v1/knowledge/documents/doc_1/reindex",
                json={"index_profile_id": "untrusted-profile"})
        assert response.status_code == 422
        reindex.assert_not_awaited()

    async def test_source_locator_is_forwarded_under_owner_scope(self, authenticated_actor):
        block = {"block_id": "block_1", "section_id": "section_1", "kind": "paragraph",
                 "start_char": 0, "end_char": 8, "line_start": 2, "line_end": 2,
                 "heading_path": ["光合作用"]}
        excerpt = {"doc_id": "doc_1", "version_id": "version_1", "parse_artifact_id": "parse_1",
                   "canonical_text_hash": "canonical-hash", "source_sha256": "source-hash",
                   "excerpt": "光合作用需要光。", "block_id": "block_1",
                   "locator": {**block, "quote_hash": "quote-hash"}, "blocks": [block], "sections": []}
        with patch("app.services.source_service.read_source",
                   AsyncMock(return_value=excerpt)) as source:
            response = await api_request("GET", "/api/v1/knowledge/documents/doc_1/source",
                params={"version_id": "version_1", "parse_artifact_id": "parse_1",
                        "block_id": "block_1", "start_char": 0, "end_char": 8})
        assert response.status_code == 200
        assert response.json()["data"]["locator"]["heading_path"] == ["光合作用"]
        assert response.json()["data"]["locator"]["line_start"] == 2
        assert response.json()["data"]["source_sha256"] == "source-hash"
        source.assert_awaited_once_with(1, "doc_1", "version_1", "parse_1", "block_1",
                                       start_char=0, end_char=8)


@pytest.mark.asyncio
class TestKnowledgeDeleteAPI:
    async def test_delete_returns_deferred_cleanup_state(self, authenticated_actor):
        with patch("app.services.source_service.revoke_document",
                   AsyncMock(return_value={"doc_id": "doc_1", "status": "deleted", "task_id": "cleanup_1"})) as revoke:
            response = await api_request("DELETE", "/api/v1/knowledge/documents/doc_1")
        assert response.status_code == 202
        assert response.json()["data"] == {"doc_id": "doc_1", "status": "deleted", "task_id": "cleanup_1"}
        revoke.assert_awaited_once_with(authenticated_actor, "doc_1")

    async def test_delete_requires_auth(self):
        with patch("app.services.source_service.revoke_document", AsyncMock()) as revoke:
            response = await api_request("DELETE", "/api/v1/knowledge/documents/doc_1")
        assert response.status_code == 401
        revoke.assert_not_awaited()
