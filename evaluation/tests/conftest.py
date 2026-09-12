import hashlib
import os
from pathlib import Path

import pytest


def pytest_configure(config):
    if config.option.basetemp is None:
        root = Path(__file__).resolve().parents[1]
        target = (root / ".pytest-tmp" / str(os.getpid())).resolve()
        if not target.is_relative_to(root):
            raise RuntimeError(
                "test scratch directory must stay inside evaluation workspace"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(target)


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_source(
    text="Plants use light. Water is required.", doc_id="doc-a", family_id="family-a"
):
    return {
        "doc_id": doc_id,
        "source_version_id": "v1",
        "parse_artifact_id": "parse-1",
        "canonical_text_hash": digest(text),
        "source_sha256": digest(text),
        "canonical_text": text,
        "family_id": family_id,
    }


def make_span(source, start, end, block_id="body"):
    return {
        **{
            key: source[key]
            for key in (
                "doc_id",
                "source_version_id",
                "parse_artifact_id",
                "canonical_text_hash",
            )
        },
        "block_id": block_id,
        "start_char": start,
        "end_char": end,
        "quote_hash": digest(source["canonical_text"][start:end]),
    }


def make_evidence(source, start, end, eid="e1", block_id="body", **extra):
    span = make_span(source, start, end, block_id)
    excerpt = source["canonical_text"][start:end]
    return {
        "evidence_id": eid,
        "source_type": "document",
        "authorized": True,
        **{
            key: source[key]
            for key in (
                "doc_id",
                "source_version_id",
                "parse_artifact_id",
                "canonical_text_hash",
            )
        },
        "excerpt": excerpt,
        "text_hash": digest(excerpt),
        "locator": span,
        **extra,
    }


@pytest.fixture
def two_group_case():
    source = make_source()
    return {
        "schema_version": "1",
        "case_type": "retrieval",
        "sample_id": "retrieve-1",
        "family_ids": ["family-a"],
        "split": "dev",
        "source_refs": [source],
        "query": "What do plants need?",
        "expected_outcome": "answerable",
        "gold_evidence_groups": [
            {
                "group_id": "light",
                "alternatives": [{"spans": [make_span(source, 0, 17)]}],
            },
            {
                "group_id": "water",
                "alternatives": [{"spans": [make_span(source, 18, 36)]}],
            },
        ],
    }


@pytest.fixture
def retrieval_artifact(two_group_case):
    source = two_group_case["source_refs"][0]
    return {
        "schema_version": "1",
        "case_type": "retrieval",
        "sample_id": two_group_case["sample_id"],
        "status": "completed",
        "evidence": [make_evidence(source, 0, 17)],
        "context_evidence_ids": ["e1"],
        "usage": {"context_tokens": 5, "calls": []},
    }


@pytest.fixture
def quiz_case():
    source = make_source(
        "Water boils at 100 C at standard pressure. Ice melts at 0 C. Steam is gaseous water."
    )
    span = make_span(source, 0, len(source["canonical_text"]))
    return {
        "schema_version": "1",
        "case_type": "quiz",
        "sample_id": "quiz-1",
        "family_ids": ["family-a"],
        "split": "dev",
        "source_refs": [source],
        "user_input": "Create three questions about water.",
        "question_count": 3,
        "source_policy": "strict_docs",
        "expected_outcome": "generate",
        "source_sufficient": True,
        "gold_evidence_groups": [
            {"group_id": "water", "alternatives": [{"spans": [span]}]}
        ],
        "question_rubrics": [
            {
                "question_id": "q1",
                "type": "single_choice",
                "stem": "At standard pressure, when does water boil?",
                "correct_answer_texts": ["100 C"],
                "reference_explanation": "Water boils at 100 C at standard pressure.",
                "supporting_spans": [span],
                "objective_id": "boiling",
            },
            {
                "question_id": "q2",
                "type": "true_false",
                "stem": "Ice melts at 50 C.",
                "correct_answer": False,
                "reference_explanation": "Ice melts at 0 C.",
                "refutation": "Ice melts at 0 C.",
                "refutation_spans": [span],
                "supporting_spans": [span],
                "objective_id": "melting",
            },
            {
                "question_id": "q3",
                "type": "single_choice",
                "stem": "What is steam?",
                "correct_answer_texts": ["Gaseous water"],
                "reference_explanation": "Steam is gaseous water.",
                "supporting_spans": [span],
                "objective_id": "steam",
            },
        ],
        "expected_objectives": ["boiling", "melting", "steam"],
    }


@pytest.fixture
def quiz_artifact(quiz_case):
    source = quiz_case["source_refs"][0]
    return {
        "schema_version": "1",
        "case_type": "quiz",
        "sample_id": "quiz-1",
        "status": "completed",
        "evidence": [make_evidence(source, 0, len(source["canonical_text"]))],
        "context_evidence_ids": ["e1"],
        "usage": {"context_tokens": 30, "calls": []},
        "questions": [
            {
                "question_id": "q1",
                "type": "single_choice",
                "stem": "At standard pressure, when does water boil?",
                "options": [
                    {"id": "A", "text": "100 C"},
                    {"id": "B", "text": "40 C"},
                    {"id": "C", "text": "900 C"},
                ],
                "answer": ["A"],
                "explanation": "Water boils at 100 C at standard pressure.",
                "citation_refs": ["e1"],
            },
            {
                "question_id": "q2",
                "type": "true_false",
                "stem": "Ice melts at 50 C.",
                "options": [],
                "answer": False,
                "explanation": "Ice melts at 0 C.",
                "citation_refs": ["e1"],
            },
            {
                "question_id": "q3",
                "type": "single_choice",
                "stem": "What is steam?",
                "options": [
                    {"id": "A", "text": "Gaseous water"},
                    {"id": "B", "text": "Solid metal"},
                ],
                "answer": ["A"],
                "explanation": "Steam is gaseous water.",
                "citation_refs": ["e1"],
            },
        ],
    }
