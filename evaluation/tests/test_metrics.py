import copy
import json
import math

import pytest
from conftest import make_evidence, make_source, make_span
from rag_eval.metrics import cost_metrics, score_sample
from rag_eval.contracts import LEARNING_METRIC_VERSION


def test_duplicate_evidence_does_not_increase_recall(
    two_group_case, retrieval_artifact
):
    repeated = copy.deepcopy(retrieval_artifact["evidence"][0])
    repeated["evidence_id"] = "duplicate"
    retrieval_artifact["evidence"].append(repeated)
    metrics = score_sample(two_group_case, retrieval_artifact, {"metric_version": "v1"})
    assert metrics["evidence_group_recall@10"]["value"] == 0.5
    assert metrics["all_evidence@10"]["value"] == 0.0
    assert metrics["evidence_group_recall@10"]["denominator"] == 2
    json.dumps(metrics, allow_nan=False)


def test_partial_span_does_not_cover_negation(two_group_case, retrieval_artifact):
    source = two_group_case["source_refs"][0]
    retrieval_artifact["evidence"] = [make_evidence(source, 0, 12)]
    assert (
        score_sample(two_group_case, retrieval_artifact)["evidence_group_recall@10"][
            "value"
        ]
        == 0
    )


def test_adjacent_ranges_jointly_cover_required_span(
    two_group_case, retrieval_artifact
):
    source = two_group_case["source_refs"][0]
    retrieval_artifact["evidence"] = [
        make_evidence(source, 0, 8),
        make_evidence(source, 8, 17, "e2"),
    ]
    assert (
        score_sample(two_group_case, retrieval_artifact)["evidence_group_recall@10"][
            "value"
        ]
        == 0.5
    )


def test_alternative_requires_every_span(two_group_case, retrieval_artifact):
    source = two_group_case["source_refs"][0]
    two_group_case["gold_evidence_groups"] = [
        {
            "group_id": "both",
            "alternatives": [
                {"spans": [make_span(source, 0, 17), make_span(source, 18, 36)]},
                {"spans": [make_span(source, 0, 36)]},
            ],
        }
    ]
    assert (
        score_sample(two_group_case, retrieval_artifact)["evidence_group_recall@10"][
            "value"
        ]
        == 0
    )


def test_no_gold_is_not_perfect_score(two_group_case, retrieval_artifact):
    two_group_case["gold_evidence_groups"] = []
    result = score_sample(two_group_case, retrieval_artifact)[
        "evidence_group_recall@10"
    ]
    assert (
        result["status"] == "na"
        and result["value"] is None
        and result["denominator"] == 0
    )


def test_mapping_failure_preserves_unknown_bounds(two_group_case, retrieval_artifact):
    retrieval_artifact["evidence"][0]["parse_artifact_id"] = "new-parser"
    retrieval_artifact["evidence"][0]["locator"]["parse_artifact_id"] = "new-parser"
    result = score_sample(two_group_case, retrieval_artifact)[
        "evidence_group_recall@10"
    ]
    assert result["status"] == "error" and result["reason"] == "mapping_failed"
    assert result["details"]["lower_bound"] == 0
    assert result["details"]["upper_bound"] == 1


def test_final_context_is_scored_separately_from_candidates(
    two_group_case, retrieval_artifact
):
    source = two_group_case["source_refs"][0]
    retrieval_artifact["evidence"].append(make_evidence(source, 18, 36, "e2"))
    result = score_sample(two_group_case, retrieval_artifact)
    assert result["evidence_group_recall@10"]["value"] == 1
    assert result["context_evidence_group_recall"]["value"] == 0.5


def test_unicode_codepoint_offsets_do_not_use_utf16():
    source = make_source("光🌱需要水。")
    sample = {
        "case_type": "retrieval",
        "sample_id": "u",
        "source_refs": [source],
        "gold_evidence_groups": [
            {"group_id": "g", "alternatives": [{"spans": [make_span(source, 1, 2)]}]}
        ],
    }
    artifact = {
        "case_type": "retrieval",
        "sample_id": "u",
        "evidence": [make_evidence(source, 1, 2)],
    }
    assert score_sample(sample, artifact)["evidence_group_recall@10"]["value"] == 1


def test_tied_canonical_units_use_expected_rr_at_cutoff(
    two_group_case, retrieval_artifact
):
    source = two_group_case["source_refs"][0]
    retrieval_artifact["evidence"] = [make_evidence(source, 0, 36)]
    two_group_case["ranking_labels"] = [
        {"unit_id": "irrelevant", "grade": 0, "spans": [make_span(source, 0, 17)]},
        {"unit_id": "relevant", "grade": 3, "spans": [make_span(source, 18, 36)]},
    ]
    result = score_sample(two_group_case, retrieval_artifact, {"ranking_ks": [1, 2]})
    assert result["mrr@1"]["value"] == 0.5
    assert result["mrr@2"]["value"] == 0.75
    assert result["ndcg@1"]["value"] == 0.5
    assert result["ndcg@2"]["value"] == pytest.approx((1 + 1 / math.log2(3)) / 2)


def test_ndcg_ideal_uses_unretrieved_gold(two_group_case, retrieval_artifact):
    source = two_group_case["source_refs"][0]
    two_group_case["ranking_labels"] = [
        {"unit_id": "returned", "grade": 1, "spans": [make_span(source, 0, 17)]},
        {"unit_id": "missed", "grade": 3, "spans": [make_span(source, 18, 36)]},
    ]
    result = score_sample(two_group_case, retrieval_artifact, {"ranking_ks": [1]})
    assert result["ndcg@1"]["value"] == pytest.approx(1 / 7)
    assert result["mrr@1"]["value"] == 0


def test_unjudged_unit_is_not_treated_as_irrelevant(two_group_case, retrieval_artifact):
    source = two_group_case["source_refs"][0]
    two_group_case["ranking_labels"] = [
        {"unit_id": "unknown", "grade": None, "spans": [make_span(source, 0, 17)]}
    ]
    result = score_sample(two_group_case, retrieval_artifact)
    assert result["ndcg@10"]["reason"] == "unjudged_ranking_units"


def test_attempt_costs_are_accounted_without_duplicate_ledger_rows(
    two_group_case, retrieval_artifact
):
    call = {
        "call_id": "provider-request",
        "attempt": 1,
        "stage": "generation",
        "cost_cny": 0.2,
        "cost_status": "actual",
        "status": "timeout",
    }
    retry = {**call, "attempt": 2, "cost_cny": 0.3, "status": "completed"}
    retrieval_artifact["usage"]["calls"] = [call, retry, copy.deepcopy(retry)]
    scores = score_sample(two_group_case, retrieval_artifact)
    assert scores["total_cost_cny"]["value"] == 0.5
    assert scores["retry_count"]["value"] == 1


def test_unknown_bill_is_not_zero_cost(two_group_case, retrieval_artifact):
    retrieval_artifact["usage"]["calls"] = [
        {
            "call_id": "timeout",
            "stage": "generation",
            "attempt": 1,
            "cost_cny": None,
            "cost_status": "unknown",
        }
    ]
    result = score_sample(two_group_case, retrieval_artifact)["total_cost_cny"]
    assert result["status"] == "error" and result["value"] is None
    assert result["unknown_count"] == 1


def test_native_provider_stages_preserve_all_attempt_costs(
    two_group_case, retrieval_artifact
):
    first = {
        "call_id": "native-llm",
        "attempt": 1,
        "stage": "llm",
        "cost_cny": 0.2,
        "cost_status": "estimated",
        "status": "timeout",
    }
    retry = {**first, "attempt": 2, "cost_cny": 0.3, "status": "completed"}
    rerank = {
        **first,
        "call_id": "native-reranker",
        "stage": "reranker",
        "cost_cny": 0.1,
        "status": "completed",
    }
    retrieval_artifact["usage"]["calls"] = [first, retry, dict(retry), rerank]
    scores = score_sample(two_group_case, retrieval_artifact)
    assert scores["generation_cost_cny"]["value"] == pytest.approx(0.5)
    assert scores["rerank_cost_cny"]["value"] == pytest.approx(0.1)
    assert scores["total_cost_cny"]["value"] == pytest.approx(0.6)
    assert scores["provider_call_count"]["value"] == 3
    assert scores["retry_count"]["value"] == 1


@pytest.mark.parametrize(
    "native,canonical", [("llm", "generation"), ("reranker", "rerank")]
)
def test_unknown_native_provider_cost_remains_unknown_in_its_category(
    native, canonical, two_group_case, retrieval_artifact
):
    retrieval_artifact["usage"]["calls"] = [
        {
            "call_id": "known-attempt",
            "stage": native,
            "attempt": 1,
            "cost_cny": 0.2,
            "cost_status": "estimated",
        },
        {
            "call_id": "unknown-attempt",
            "stage": native,
            "attempt": 2,
            "cost_cny": None,
            "cost_status": "unknown",
        },
    ]
    scores = score_sample(two_group_case, retrieval_artifact)
    category = scores[f"{canonical}_cost_cny"]
    assert category["status"] == "error" and category["value"] is None
    assert category["unknown_count"] == 1
    assert category["details"]["known_cost_cny"] == 0.2
    assert scores["total_cost_cny"]["status"] == "error"


def test_policy_observations_cannot_pass_with_unauthorized_source():
    sample = {
        "sample_id": "policy-1",
        "case_type": "policy",
        "expected_status": "denied",
        "expected_error_code": "forbidden",
    }
    artifact = {
        "sample_id": "policy-1",
        "case_type": "policy",
        "status": "completed",
        "observations": {
            "actual_status": "denied",
            "error_code": "forbidden",
            "unauthorized_source_count": 1,
            "production_side_effect_count": 0,
            "stale_publish_count": 0,
        },
    }
    scores = score_sample(sample, artifact)
    assert scores["policy_expected_result"]["value"] == 1
    assert scores["authorization_safety"]["value"] == 0


def test_case_type_mismatch_is_rejected(two_group_case, retrieval_artifact):
    retrieval_artifact["case_type"] = "quiz"
    with pytest.raises(ValueError, match="case_type"):
        score_sample(two_group_case, retrieval_artifact)


def test_cross_block_chunk_coverage_uses_original_global_ranges(
    two_group_case, retrieval_artifact
):
    source = two_group_case["source_refs"][0]
    two_group_case["gold_evidence_groups"][1]["alternatives"][0]["spans"][0][
        "block_id"
    ] = "paragraph-2"
    retrieval_artifact["evidence"] = [
        make_evidence(source, 0, 36, block_id="paragraph-1")
    ]
    assert (
        score_sample(two_group_case, retrieval_artifact)["evidence_group_recall@10"][
            "value"
        ]
        == 1
    )


def test_corrupt_evidence_does_not_earn_gold_coverage(
    two_group_case, retrieval_artifact
):
    retrieval_artifact["evidence"][0]["excerpt"] = "fabricated text"
    assert (
        score_sample(two_group_case, retrieval_artifact)["evidence_group_recall@10"][
            "value"
        ]
        == 0
    )


def test_missing_call_ledger_is_unknown_cost(two_group_case, retrieval_artifact):
    retrieval_artifact["usage"].pop("calls")
    result = score_sample(two_group_case, retrieval_artifact)["total_cost_cny"]
    assert result["status"] == "error" and result["reason"] == "call_ledger_unreported"


def test_frozen_ranking_pool_cannot_ignore_unjudged_returned_text(
    two_group_case, retrieval_artifact
):
    source = two_group_case["source_refs"][0]
    two_group_case["ranking_labels"] = [
        {"unit_id": "known", "grade": 3, "spans": [make_span(source, 0, 17)]}
    ]
    two_group_case["ranking_pool_complete"] = True
    retrieval_artifact["evidence"] = [make_evidence(source, 0, 36)]
    assert (
        score_sample(two_group_case, retrieval_artifact)["ndcg@10"]["reason"]
        == "unjudged_ranking_units"
    )


def test_native_retrieval_trace_preserves_candidates_separately_from_context(
    two_group_case, retrieval_artifact
):
    source = two_group_case["source_refs"][0]
    candidate = make_evidence(source, 18, 36, eid="e2")
    native = {
        "schema_version": "retrieval-artifact.v1",
        "case_type": "retrieval",
        "run_id": "eval-1",
        "evidence": retrieval_artifact["evidence"],
        "trace": {
            "sample_id": two_group_case["sample_id"],
            "candidates": [*retrieval_artifact["evidence"], candidate],
            "provided_evidence_ids": ["e1"],
            "context_tokens": 15,
        },
        "usage": {"calls": [], "stage_ms": {"retrieval": 21}},
    }
    result = score_sample(two_group_case, native)
    assert result["evidence_group_recall@10"]["value"] == 1
    assert result["context_evidence_group_recall"]["value"] == 0.5
    assert result["context_tokens"]["value"] == 15
    assert result["retrieval_latency_ms"]["value"] == 21


def test_metric_values_expose_shared_applicability_and_error_counts(
    two_group_case, retrieval_artifact
):
    results = score_sample(two_group_case, retrieval_artifact)
    assert results["evidence_group_recall@10"]["applicable_count"] == 1
    assert results["evidence_group_recall@10"]["error_count"] == 0
    assert results["ndcg@10"]["applicable_count"] == 0


def personal_call(**changes):
    return {
        "call_id": "personal-call", "attempt": 1, "stage": "llm",
        "config_source": "user", "cost_status": "not_applicable",
        "cost_cny": None, "reserved_cost_cny": None, "status": "completed",
        "input_tokens": 12, "output_tokens": 5, **changes,
    }


@pytest.mark.parametrize("status", ["completed", "timeout", "unknown"])
def test_personal_metrics_are_na_money_but_keep_technical_usage(status):
    call = personal_call(status=status, error_type="ReadTimeout" if status != "completed" else None)
    scores = cost_metrics(
        {"case_type": "practice_generation", "usage": {
            "calls": [call, dict(call)], "ledger_complete": True,
            "reserved_cost_cny": None, "unknown_reserved_cost_cny": None,
            "unknown_call_count": 1,
        }}, {"metric_version": LEARNING_METRIC_VERSION}, 3,
    )
    for name in ("total_cost_cny", "generation_cost_cny", "reserved_cost_cny", "unknown_reserved_cost_cny", "cost_per_valid_question_cny"):
        metric = scores[name]
        assert metric["status"] == "na" and metric["value"] is None
        assert metric["unknown_count"] == 0 and metric["unit"].startswith("CNY")
    assert scores["provider_call_count"]["value"] == 1
    assert scores["input_tokens"]["value"] == 12
    assert scores["output_tokens"]["value"] == 5
    assert scores["unknown_call_count"]["value"] == 0
    assert scores["provider_error_rate"]["value"] == int(status != "completed")


def test_mixed_metrics_keep_only_system_money_without_masking_outstanding_aggregate():
    usage = {
        "calls": [personal_call(), {
            "call_id": "system-call", "attempt": 1, "stage": "embedding",
            "config_source": "system", "cost_status": "estimated", "status": "completed",
            "cost_cny": "0.02", "reserved_cost_cny": "0.05", "input_tokens": 8, "output_tokens": 0,
        }],
        "ledger_complete": True, "cost_status_cny": "estimated",
        "reserved_cost_cny": "0", "unknown_reserved_cost_cny": "0",
    }
    scores = cost_metrics(
        {"case_type": "practice_generation", "usage": usage},
        {"metric_version": LEARNING_METRIC_VERSION}, 2,
    )
    assert scores["total_cost_cny"]["value"] == pytest.approx(0.02)
    assert scores["generation_cost_cny"]["status"] == "na"
    assert scores["embedding_cost_cny"]["value"] == pytest.approx(0.02)
    assert scores["cost_per_valid_question_cny"]["value"] == pytest.approx(0.01)
    assert scores["reserved_cost_cny"]["value"] == 0
    assert scores["unknown_reserved_cost_cny"]["value"] == 0
    assert scores["provider_call_count"]["value"] == 2


def test_system_llm_reranker_keeps_separate_money_category():
    usage = {"calls": [personal_call(), personal_call(
        call_id="system-ranking", config_source="system", purpose="reranker",
        cost_cny="0.1", cost_status="estimated", reserved_cost_cny="0.2",
    )]}
    scores = cost_metrics(
        {"case_type": "practice_generation", "usage": usage},
        {"metric_version": LEARNING_METRIC_VERSION},
    )
    assert scores["generation_cost_cny"]["status"] == "na"
    assert scores["rerank_cost_cny"]["value"] == pytest.approx(0.1)
    assert scores["total_cost_cny"]["value"] == pytest.approx(0.1)


@pytest.mark.parametrize("source", [None, "system"])
def test_missing_or_system_source_never_becomes_nonbillable_from_null_cost(source):
    scores = cost_metrics(
        {"case_type": "practice_generation", "usage": {"calls": [personal_call(
            config_source=source, cost_status="unknown"
        )]}}, {"metric_version": LEARNING_METRIC_VERSION},
    )
    assert scores["total_cost_cny"]["status"] == "error"
    assert scores["total_cost_cny"]["unknown_count"] == 1


def test_personal_cost_na_does_not_hide_incomplete_call_ledger():
    scores = cost_metrics(
        {"case_type": "practice_generation", "usage": {
            "calls": [personal_call()], "ledger_complete": False,
        }}, {"metric_version": LEARNING_METRIC_VERSION}, 3,
    )
    assert scores["total_cost_cny"]["status"] == "error"
    assert scores["reserved_cost_cny"]["status"] == "error"
    assert scores["cost_per_valid_question_cny"]["status"] == "error"
    assert scores["provider_call_count"]["status"] == "error"
