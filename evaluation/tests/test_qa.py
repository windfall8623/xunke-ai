"""Deterministic QA evidence metrics never claim calibrated semantic quality."""

import copy

import pytest
from conftest import make_evidence, make_source, make_span
from rag_eval.datasets import validate_dataset
from rag_eval.metrics import score_sample


def qa_pair():
    source = make_source("Juniper station opens at 08:30. It closes at 17:45.")
    text = source["canonical_text"]
    split = text.index(" It")
    sample = {
        "schema_version": "1",
        "case_type": "qa",
        "sample_id": "qa-1",
        "split": "dev",
        "family_ids": [source["family_id"]],
        "source_refs": [source],
        "question": "When does Juniper station open and close?",
        "history": [],
        "expected_answer_status": "answered",
        "annotation": {"provenance": "model_draft", "human_reviewed": False},
        "gold_evidence_groups": [
            {
                "group_id": "opening",
                "alternatives": [{"spans": [make_span(source, 0, split)]}],
            },
            {
                "group_id": "closing",
                "alternatives": [{"spans": [make_span(source, split + 1, len(text))]}],
            },
        ],
    }
    artifact = {
        "schema_version": "1",
        "case_type": "qa",
        "sample_id": "qa-1",
        "answer_status": "answered",
        "run_id": "run-1",
        "status": "completed",
        "blocks": [
            {"block_id": "b1", "kind": "fact", "text": text, "citation_refs": ["e1"]}
        ],
        "evidence": [make_evidence(source, 0, len(text))],
        "trace": [{"stage": "retrieve", "context_tokens": 40}],
        "usage": {"calls": [], "stage_ms": {"qa": 3}},
    }
    return sample, artifact


def test_qa_scores_status_citations_and_cited_evidence_without_quiz_metrics():
    sample, artifact = qa_pair()
    scores = score_sample(sample, artifact)
    for key in (
        "qa_answer_status_match",
        "qa_answer_structure_validity",
        "qa_citation_validity",
        "qa_fact_citation_coverage",
        "qa_evidence_group_recall",
        "qa_all_evidence_hit",
        "context_evidence_group_recall",
        "context_budget_pass",
    ):
        assert scores[key]["value"] == 1, (key, scores[key])
    assert scores["qa_citation_validity"]["details"]["locator_valid_count"] == 1
    assert scores["context_tokens"]["value"] == 40
    assert "question_schema_pass" not in scores
    assert "answer_correctness" not in scores
    assert scores["qa_failure_behavior_match"]["status"] == "na"


def test_semantic_metrics_stay_not_evaluated_even_with_self_validation_and_claimed_reviews():
    sample, artifact = qa_pair()
    artifact["semantic_validation"] = {"passed": True}
    artifact["semantic_reviews"] = [
        {"block_id": "b1", "correctness": True, "faithfulness": True}
    ]
    scores = score_sample(sample, artifact, {"external_judge": {"calibrated": True}})
    for key in ("qa_correctness", "qa_faithfulness"):
        assert scores[key]["status"] == "na"
        assert scores[key]["value"] is None
        assert scores[key]["reason"] == "not_evaluated"


@pytest.mark.parametrize(
    "mutation",
    ["unknown_id", "hash", "locator", "owner", "duplicate_id", "not_in_context"],
)
def test_forged_or_unprovided_citations_fail_validity(mutation):
    sample, artifact = qa_pair()
    evidence = artifact["evidence"][0]
    if mutation == "unknown_id":
        artifact["blocks"][0]["citation_refs"] = ["invented"]
    elif mutation == "hash":
        evidence["text_hash"] = "0" * 64
    elif mutation == "locator":
        evidence["locator"]["end_char"] += 1
    elif mutation == "owner":
        sample["source_refs"][0]["owner_id"] = 7
        evidence["owner_id"] = 8
    elif mutation == "duplicate_id":
        artifact["evidence"].append(copy.deepcopy(evidence))
    elif mutation == "not_in_context":
        artifact["context_evidence_ids"] = []
    scores = score_sample(sample, artifact)
    assert scores["qa_citation_validity"]["value"] == 0
    assert scores["qa_fact_citation_coverage"]["value"] == 0


def test_source_text_unavailable_is_unknown_not_a_passing_locator():
    sample, artifact = qa_pair()
    sample["source_refs"][0].pop("canonical_text")
    value = score_sample(sample, artifact)["qa_citation_validity"]
    assert value["status"] == "error"
    assert value["value"] is None
    assert value["reason"] == "source_validation_unreported"


def test_uncited_retrieved_evidence_does_not_improve_answer_evidence_recall():
    sample, artifact = qa_pair()
    source = sample["source_refs"][0]
    end = source["canonical_text"].index(" It")
    artifact["evidence"].insert(0, make_evidence(source, 0, end, eid="cited"))
    artifact["blocks"][0]["citation_refs"] = ["cited"]
    scores = score_sample(sample, artifact)
    assert scores["context_evidence_group_recall"]["value"] == 1
    assert scores["qa_evidence_group_recall"]["value"] == 0.5
    assert scores["qa_all_evidence_hit"]["value"] == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "arbitrary_notice",
        "empty_blocks",
        "duplicate_blocks",
        "uncited_fact",
        "wrong_status",
    ],
)
def test_answer_structure_rejects_notice_bypass_and_invalid_fact_blocks(mutation):
    sample, artifact = qa_pair()
    if mutation == "arbitrary_notice":
        artifact["blocks"][0].update(kind="notice", citation_refs=[])
        artifact["answer_status"] = "insufficient_evidence"
    elif mutation == "empty_blocks":
        artifact["blocks"] = []
    elif mutation == "duplicate_blocks":
        artifact["blocks"].append(copy.deepcopy(artifact["blocks"][0]))
    elif mutation == "uncited_fact":
        artifact["blocks"][0]["citation_refs"] = []
    elif mutation == "wrong_status":
        artifact["answer_status"] = "needs_clarification"
    assert score_sample(sample, artifact)["qa_answer_structure_validity"]["value"] == 0


def test_conflict_requires_separately_cited_fact_blocks():
    sample, artifact = qa_pair()
    sample["expected_answer_status"] = artifact["answer_status"] = "conflicting_sources"
    artifact["evidence"].append(
        {**copy.deepcopy(artifact["evidence"][0]), "evidence_id": "e2"}
    )
    artifact["blocks"][0]["citation_refs"] = ["e1", "e2"]
    assert score_sample(sample, artifact)["qa_answer_structure_validity"]["value"] == 0


def test_fixed_insufficient_notice_is_valid_but_not_a_fact():
    sample, artifact = qa_pair()
    sample.update(
        expected_answer_status="insufficient_evidence", gold_evidence_groups=[]
    )
    artifact.update(
        answer_status="insufficient_evidence",
        evidence=[],
        blocks=[
            {
                "block_id": "notice",
                "kind": "notice",
                "citation_refs": [],
                "text": "在当前选定的资料中未找到足够依据，暂时无法回答。",
            }
        ],
    )
    scores = score_sample(sample, artifact)
    assert scores["qa_answer_status_match"]["value"] == 1
    assert scores["qa_answer_structure_validity"]["value"] == 1
    assert scores["qa_fact_citation_coverage"]["status"] == "na"


def test_technical_failure_is_not_successful_insufficient_evidence():
    sample, artifact = qa_pair()
    sample["expected_answer_status"] = "insufficient_evidence"
    artifact.update(
        status="failed",
        answer_status="insufficient_evidence",
        error_code="BUDGET_EXCEEDED",
        blocks=[],
    )
    scores = score_sample(sample, artifact)
    assert scores["qa_answer_status_match"]["value"] == 0
    assert scores["service_failure"]["value"] == 1


@pytest.mark.parametrize(
    "published,code,expected",
    [
        (False, "SOURCE_UNAVAILABLE", 1),
        (True, "SOURCE_UNAVAILABLE", 0),
        (False, "RETRIEVAL_UNAVAILABLE", 0),
    ],
)
def test_expected_failure_requires_actual_error_and_no_published_answer(
    published, code, expected
):
    sample, artifact = qa_pair()
    sample.update(expected_answer_status=None, expected_error_code="SOURCE_UNAVAILABLE")
    artifact.update(status="failed", error_code=code)
    if not published:
        artifact.pop("answer_status")
        artifact.pop("blocks")
        artifact["evidence"] = []
    scores = score_sample(sample, artifact)
    assert scores["qa_failure_behavior_match"]["value"] == expected
    assert scores["qa_answer_status_match"]["status"] == "na"


def draft_dataset():
    sample, _ = qa_pair()
    source = {**sample["source_refs"][0], "license": "synthetic_fixture"}
    return {"schema_version": "1", "state": "draft", "sources": [source]}, [sample]


def test_qa_draft_validates_but_is_not_human_gold():
    manifest, samples = draft_dataset()
    report = validate_dataset(manifest, samples)
    assert report["valid"], report["errors"]
    assert report["counts"]["qa"] == 1
    assert report["review"]["human_reviewed_count"] == 0
    assert report["formal_gold_eligible"] is False
    assert report["freezable"] is False


@pytest.mark.parametrize(
    "change,code",
    [
        ({"question": "  "}, "qa_question_invalid"),
        ({"expected_answer_status": "failed"}, "qa_expected_status_invalid"),
        ({"expected_answer_status": None}, "qa_expected_error_required"),
        ({"expected_error_code": "SOURCE_UNAVAILABLE"}, "qa_status_error_conflict"),
        (
            {
                "history": [
                    {"question": "q", "answer": "a", "scope_fingerprint": "foreign"}
                ]
            },
            "qa_history_invalid",
        ),
        ({"source_refs": []}, "qa_source_scope_missing"),
        ({"gold_evidence_groups": []}, "qa_answer_gold_missing"),
    ],
)
def test_qa_dataset_rejects_invalid_cases(change, code):
    manifest, samples = draft_dataset()
    samples[0].update(change)
    report = validate_dataset(manifest, samples)
    assert not report["valid"]
    assert code in {error["code"] for error in report["errors"]}


@pytest.mark.parametrize("status", [[], {}, 1, False])
def test_wrongly_typed_qa_sample_status_is_a_validation_error(status):
    manifest, samples = draft_dataset()
    samples[0]["expected_answer_status"] = status
    report = validate_dataset(manifest, samples)
    assert not report["valid"]
    assert "qa_expected_status_invalid" in {error["code"] for error in report["errors"]}


@pytest.mark.parametrize("field", ["answer_status", "status"])
@pytest.mark.parametrize("status", [[], {}, 1, False])
def test_wrongly_typed_artifact_status_does_not_crash_structure_scoring(field, status):
    sample, artifact = qa_pair()
    artifact[field] = status
    scores = score_sample(sample, artifact)
    assert scores["qa_answer_structure_validity"]["value"] == 0


def test_missing_blocks_is_invalid_structure_without_crashing_other_qa_metrics():
    sample, artifact = qa_pair()
    artifact["blocks"] = None
    scores = score_sample(sample, artifact)
    assert scores["qa_answer_structure_validity"]["value"] == 0
