"""Public RAG identity, source policy, and invalid evidence regression tests."""

import hashlib
import importlib

import pytest
from pydantic import ValidationError


def test_rag_contract_module_exists():
    assert importlib.util.find_spec("app.rag.contracts") is not None


def document_payload():
    return {
        "source_type": "document",
        "evidence_id": "ev_1",
        "owner_id": 7,
        "namespace": "production",
        "title": "光合作用",
        "doc_id": "doc_1",
        "document_version_id": "v1",
        "parse_artifact_id": "p1",
        "index_build_id": "b1",
        "attempt_id": "a1",
        "chunk_id": "c1",
        "excerpt": "光合作用需要光。",
        "text_hash": hashlib.sha256("光合作用需要光。".encode()).hexdigest(),
        "locator": {
            "source_sha256": "a" * 64,
            "parse_artifact_id": "p1",
            "canonical_text_hash": "b" * 64,
            "parser_version": "txt-1",
            "normalizer_version": "newline-1",
            "block_id": "p1:block_1",
            "start_char": 0,
            "end_char": 8,
            "quote_hash": hashlib.sha256("光合作用需要光。".encode()).hexdigest(),
            "paragraph": 1,
        },
    }


def test_document_citation_requires_parse_identity():
    from app.rag.contracts import DocumentEvidence

    payload = document_payload()
    evidence = DocumentEvidence.model_validate(payload)
    assert evidence.locator.end_char == 8
    payload.pop("parse_artifact_id")
    with pytest.raises(ValidationError):
        DocumentEvidence.model_validate(payload)


@pytest.mark.parametrize(
    "change",
    [
        {"text_hash": "c" * 64},
        {"excerpt": "光合作用需要光😀。"},
        {"parse_artifact_id": "other"},
        {"locator": {**document_payload()["locator"], "start_char": 8, "end_char": 0}},
        {"locator": {**document_payload()["locator"], "page": 0}},
    ],
)
def test_document_citation_rejects_corrupted_anchor(change):
    from app.rag.contracts import DocumentEvidence

    with pytest.raises(ValidationError):
        DocumentEvidence.model_validate({**document_payload(), **change})


def test_web_evidence_requires_snapshot_not_document_optional_fields():
    from app.rag.contracts import WebEvidence

    payload = {
        "source_type": "web",
        "evidence_id": "e2",
        "owner_id": 7,
        "namespace": "production",
        "title": "Page",
        "url": "https://example.org/page",
        "fetched_at": "2026-09-07T00:00:00Z",
        "snapshot_id": "s1",
        "snapshot_hash": "a" * 64,
        "excerpt": "hello",
        "text_hash": hashlib.sha256(b"hello").hexdigest(),
        "locator": {
            "block_id": "s1:block1",
            "start_char": 0,
            "end_char": 5,
            "quote_hash": hashlib.sha256(b"hello").hexdigest(),
        },
    }
    assert WebEvidence.model_validate(payload).snapshot_id == "s1"
    payload.pop("snapshot_hash")
    with pytest.raises(ValidationError):
        WebEvidence.model_validate(payload)


def test_pipeline_config_hash_covers_embedding_and_budget_but_is_stable():
    from app.rag.contracts import PipelineConfig

    first = PipelineConfig()
    assert first.pipeline_config_hash == PipelineConfig().pipeline_config_hash
    changed = first.model_copy(update={"context_token_budget": 4000})
    assert changed.pipeline_config_hash != first.pipeline_config_hash


def test_question_identity_cannot_overflow_durable_answer_storage():
    from app.rag.contracts import ArtifactQuestion

    question = {
        "id": "q" * 64,
        "type": "single",
        "stem": "光合作用需要什么？",
        "options": [{"key": "A", "text": "光"}, {"key": "B", "text": "无光"}],
        "answer": ["A"],
        "explanation": "需要光。",
        "knowledge_point": "光合作用",
        "difficulty": "easy",
    }
    assert len(ArtifactQuestion.model_validate(question).id) == 64
    with pytest.raises(ValidationError):
        ArtifactQuestion.model_validate({**question, "id": "q" * 65})
