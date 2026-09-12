"""Search evidence reaches the artifact pipeline only as authorized context."""
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.rag.contracts import QuizSpec, ResolvedScope, RetrievalResult, ValidationResult, WebEvidence
from app.rag.pipeline import PipelinePorts, generate_quiz_artifact
from tests.rag.test_artifact_pipeline import context_and_scope, quiz_for, strict_spec


async def semantic_acceptance(*args):
    return ValidationResult(passed=True, semantic_status="passed",
                            semantic_details={"validator": "explicit-unit-test-fixture"})


@pytest.mark.asyncio
async def test_quiz_generate_with_explicit_web_evidence_context():
    document, actor, context, scope = context_and_scope()
    excerpt = "光合作用需要光。"
    text_hash = hashlib.sha256(excerpt.encode()).hexdigest()
    web = WebEvidence(
        evidence_id="web_1", owner_id=actor.owner_id, namespace=scope.namespace,
        title="合成公开页面", url="https://example.org/synthetic-source",
        fetched_at="2026-09-07T10:00:00Z", snapshot_id="snapshot_1",
        snapshot_hash=text_hash, excerpt=excerpt, text_hash=text_hash,
        locator={"block_id": "snapshot_1:block_1", "start_char": 0, "end_char": len(excerpt), "quote_hash": text_hash},
    )
    observed = []

    async def generate(spec, pack, coverage, attempt, feedback=None):
        observed.extend(pack.evidence)
        return quiz_for(spec, pack, coverage)

    search = AsyncMock(return_value=[web])
    spec = strict_spec().model_copy(update={"source_policy": "doc_plus_web"})
    artifact = await generate_quiz_artifact(
        spec, actor, context,
        PipelinePorts(
            retrieve=AsyncMock(return_value=RetrievalResult(evidence=[document], candidates=[document])),
            generate=generate, reauthorize=AsyncMock(return_value=scope), web_search=search,
            semantic_validator=semantic_acceptance,
        ),
        resolved_scope=scope,
    )
    search.assert_awaited_once()
    assert search.await_args.args[:3] == (spec.user_input, scope, context)
    assert any(item.source_type == "web" and item.snapshot_hash == text_hash for item in observed)
    assert "web_1" in artifact.evidence_pack.provided_evidence_ids
    assert artifact.source_status == "grounded"


@pytest.mark.asyncio
async def test_topic_with_empty_search_keeps_model_only_status_and_no_citations():
    _, actor, context, _ = context_and_scope()
    scope = ResolvedScope(owner_id=actor.owner_id, namespace=context.storage_namespace)
    spec = QuizSpec(user_input="光合作用", question_count=3, source_policy="topic")
    retrieval = AsyncMock(side_effect=AssertionError("Topic mode must not read the private library"))

    async def generate(spec, pack, coverage, attempt, feedback=None):
        assert not pack.evidence
        return quiz_for(spec, pack, coverage)

    search = AsyncMock(return_value=[])
    artifact = await generate_quiz_artifact(
        spec, actor, context,
        PipelinePorts(retrieve=retrieval, generate=generate, reauthorize=AsyncMock(return_value=scope),
                      web_search=search, semantic_validator=semantic_acceptance),
        resolved_scope=scope,
    )
    assert artifact.source_status == "model_only"
    assert artifact.evidence_pack.provided_evidence_ids == []
    assert all(not question.citation_refs for question in artifact.questions)
    retrieval.assert_not_awaited()
    search.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_quiz_passes_search_context_to_prompt():
    """generate_quiz 应将 search_context 正确传入 prompt 模板"""
    mock_llm_response = MagicMock()
    mock_llm_response.content = '''{
        "title": "测试",
        "summary": "测试摘要",
        "questions": [{
            "id": "q1", "type": "single", "stem": "题干",
            "options": [{"key": "A", "text": "A"}, {"key": "B", "text": "B"},
                        {"key": "C", "text": "C"}, {"key": "D", "text": "D"}],
            "answer": ["A"], "explanation": "讲解",
            "knowledge_point": "知识点", "difficulty": "easy"
        }]
    }'''

    mock_chain = MagicMock()
    mock_chain.ainvoke = AsyncMock(return_value=mock_llm_response)

    with (
        patch("app.llm.quiz_chain.get_chat_model") as mock_get_model,
        patch("app.llm.quiz_chain.ChatPromptTemplate") as mock_prompt_cls,
    ):
        mock_prompt = MagicMock()
        mock_prompt_cls.from_messages.return_value = mock_prompt
        # prompt | llm 返回 mock_chain
        mock_prompt.__or__ = MagicMock(return_value=mock_chain)

        mock_get_model.return_value = MagicMock()

        from app.llm.quiz_chain import generate_quiz

        result = await generate_quiz(
            user_input="Harness",
            search_context="Harness 是一个 CD 平台",
        )

        assert result.title == "测试"
        # 验证 ainvoke 调用时传入了 search_context_section
        call_args = mock_chain.ainvoke.call_args
        invoke_dict = call_args[0][0] if call_args[0] else call_args.kwargs
        assert "search_context_section" in invoke_dict
        assert "Harness" in invoke_dict["search_context_section"]
