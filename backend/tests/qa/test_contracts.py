"""Public QA inputs and the evidence boundary reject unsafe/unbounded payloads."""

import pytest
from pydantic import ValidationError

from app.rag.contracts import DocumentEvidence, text_hash


def evidence():
    quote = "光合作用需要光。"
    return DocumentEvidence(
        evidence_id="e1",
        owner_id=7,
        namespace="production",
        title="植物笔记",
        excerpt=quote,
        text_hash=text_hash(quote),
        doc_id="d1",
        document_version_id="v1",
        parse_artifact_id="p1",
        index_build_id="b1",
        attempt_id="a1",
        chunk_id="n1",
        locator={
            "source_sha256": "0" * 64,
            "parse_artifact_id": "p1",
            "canonical_text_hash": "0" * 64,
            "parser_version": "test",
            "normalizer_version": "test",
            "block_id": "block1",
            "start_char": 0,
            "end_char": len(quote),
            "quote_hash": text_hash(quote),
        },
    )


def artifact_data():
    return dict(
        run_id="qa-run",
        answer_status="answered",
        blocks=[
            dict(
                block_id="b1", kind="fact", text="光是所需条件。", citation_refs=["e1"]
            )
        ],
        evidence=[evidence()],
        retrieval_query="光合作用需要什么？",
        scope_fingerprint="0" * 64,
        pipeline_config_hash="1" * 64,
    )


def test_public_question_cannot_be_blank_or_unbounded():
    from app.models.qa import QaMessageCreate

    for value in ("   ", "x" * 2001):
        with pytest.raises(ValidationError):
            QaMessageCreate(content=value, scope_revision=1)
    assert QaMessageCreate(content=" 为什么？ ", scope_revision=1).content == "为什么？"


def test_artifact_rejects_invented_citations_and_duplicate_evidence():
    from app.qa.contracts import ChatAnswerArtifact

    data = artifact_data()
    assert ChatAnswerArtifact(**data).blocks[0].citation_refs == ["e1"]
    data["blocks"][0]["citation_refs"] = ["made-up"]
    with pytest.raises(ValidationError):
        ChatAnswerArtifact(**data)
    data = artifact_data()
    data["evidence"].append(evidence())
    with pytest.raises(ValidationError):
        ChatAnswerArtifact(**data)


def test_answer_requires_cited_facts_and_distinguishes_abstention():
    from app.qa.contracts import ChatAnswerPayload

    for status, kind in (
        ("answered", "notice"),
        ("partial", "notice"),
        ("insufficient_evidence", "fact"),
    ):
        with pytest.raises(ValidationError):
            ChatAnswerPayload(
                answer_status=status,
                blocks=[
                    {
                        "block_id": "b1",
                        "kind": kind,
                        "text": "没有依据的断言",
                        "citation_refs": [],
                    }
                ],
            )
    answer = ChatAnswerPayload(
        answer_status="insufficient_evidence",
        blocks=[
            {
                "block_id": "b1",
                "kind": "notice",
                "text": "所选资料没有足够依据。",
                "citation_refs": [],
            }
        ],
    )
    assert answer.answer_status == "insufficient_evidence"


def test_history_keeps_only_recent_complete_turns_from_same_scope():
    from app.qa.contracts import ChatHistoryTurn, select_history

    turns = [
        ChatHistoryTurn(question=str(i), answer=f"答{i}", scope_fingerprint="current")
        for i in range(8)
    ]
    turns.insert(
        7, ChatHistoryTurn(question="秘密", answer="旧内容", scope_fingerprint="old")
    )
    selected = select_history(turns, "current")
    assert [item.question for item in selected] == ["2", "3", "4", "5", "6", "7"]


def test_history_budget_never_truncates_a_question_or_answer():
    from app.qa.contracts import ChatHistoryTurn, select_history

    turns = [
        ChatHistoryTurn(question="older", answer="a" * 7900, scope_fingerprint="s"),
        ChatHistoryTurn(question="recent", answer="光" * 50, scope_fingerprint="s"),
    ]
    selected = select_history(turns, "s")
    assert [(turn.question, turn.answer) for turn in selected] == [
        ("recent", "光" * 50)
    ]


def test_artifact_requires_independent_evidence_for_conflict():
    from app.qa.contracts import ChatAnswerArtifact

    data = artifact_data()
    data["answer_status"] = "conflicting_sources"
    with pytest.raises(ValidationError):
        ChatAnswerArtifact(**data)


def test_feedback_requires_explicit_consent_and_bounded_comment():
    from app.models.qa import QaFeedbackBody

    assert QaFeedbackBody(rating="helpful").evaluation_consent is False
    with pytest.raises(ValidationError):
        QaFeedbackBody(rating="helpful", comment="a" * 2001)
