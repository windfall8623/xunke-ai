import copy

import pytest
from rag_eval.comparison import compare_runs


def metric(numerator, denominator=1, **extra):
    return {
        "status": "ok",
        "value": numerator / denominator,
        "numerator": numerator,
        "denominator": denominator,
        "unit": "ratio",
        "metric_version": "v1",
        "unknown_count": 0,
        **extra,
    }


def run(rows, **manifest_changes):
    ids = sorted({row["sample_id"] for row in rows})
    return {
        "status": "completed",
        "manifest": {
            "dataset_hash": "same-dataset",
            "annotation_version": "v1",
            "metric_version": "v1",
            "judge_config_hash": "human-v1",
            "cache_protocol": "cold",
            "context_token_budget": 6000,
            "split": "locked_test",
            "repeat_count": 2,
            "dataset_state": "frozen",
            "gold_reviewed": True,
            "judge_calibrated": True,
            "protocol_frozen": True,
            "planned_sample_ids": ids,
            "cost_estimate": {"max_cost_cny": 100, "kind": "conservative_ceiling"},
            **manifest_changes,
        },
        "results": rows,
    }


def result(
    sample_id, repeat_index, numerator, denominator=3, family_ids=None, **metrics
):
    return {
        "sample_id": sample_id,
        "repeat_index": repeat_index,
        "family_ids": family_ids or [f"family-{sample_id}"],
        "split": "locked_test",
        "case_type": "quiz",
        "status": "completed",
        "metrics": {
            "valid_question_yield": metric(numerator, denominator),
            "total_cost_cny": metric(0.01, unit="CNY"),
            **metrics,
        },
    }


PROTOCOL = {
    "primary_metric": "valid_question_yield",
    "noninferiority_metrics": {},
    "hard_gates": {},
    "bootstrap_iterations": 200,
    "seed": 29,
    "min_locked_clusters": 20,
    "required_metrics": ["valid_question_yield"],
}


def test_expired_raw_artifacts_keep_metrics_but_block_formal_improvement():
    rows = [result(str(i), repeat, 2) for i in range(20) for repeat in range(2)]
    baseline = run(rows)
    candidate = run(
        copy.deepcopy(rows), raw_artifacts_status="expired", reproducible=False
    )
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["comparison_eligible"] is False
    assert "raw_artifacts_expired" in report["ineligibility_reasons"]
    assert report["metrics"]["valid_question_yield"]["candidate"][
        "value"
    ] == pytest.approx(2 / 3)


def test_repeats_average_within_request_before_original_yield_formula():
    rows = [
        result("a", 0, 3),
        result("a", 1, 0),
        result("b", 0, 5, 5),
        result("b", 1, 5, 5),
    ]
    report = compare_runs(run(rows), run(rows), PROTOCOL)
    score = report["metrics"]["valid_question_yield"]
    assert score["baseline"]["value"] == pytest.approx(6.5 / 8)
    assert score["baseline"]["numerator"] == 6.5
    assert score["baseline"]["denominator"] == 8
    assert report["sample_count"] == 2 and report["cluster_count"] == 2


def test_connected_multidocument_families_form_one_resampling_cluster():
    rows = [
        result("a", repeat, 2, family_ids=["family-1", "family-2"])
        for repeat in range(2)
    ]
    rows += [
        result("b", repeat, 3, family_ids=["family-2", "family-3"])
        for repeat in range(2)
    ]
    report = compare_runs(run(rows), run(rows), PROTOCOL)
    assert report["family_count"] == 3 and report["cluster_count"] == 1
    assert report["provisional"] is True and report["comparison_eligible"] is False


def test_unknown_core_metric_blocks_proven_improvement():
    baseline = run([result("a", repeat, 0) for repeat in range(2)])
    candidate = run([result("a", repeat, 2) for repeat in range(2)])
    candidate["results"][0]["metrics"]["valid_question_yield"] = metric(
        1,
        3,
        status="error",
        value=None,
        unknown_count=2,
        reason="judge_timeout",
        details={"lower_bound": 1 / 3, "upper_bound": 1},
    )
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["decision"] != "improved"
    assert "unresolved_core_metrics" in report["ineligibility_reasons"]
    assert report["metrics"]["valid_question_yield"]["candidate"][
        "lower_bound"
    ] == pytest.approx(0.5)
    assert report["metrics"]["valid_question_yield"]["candidate"][
        "upper_bound"
    ] == pytest.approx(5 / 6)


def test_different_judge_or_cache_protocol_is_exploratory_only():
    rows = [result("a", repeat, 3) for repeat in range(2)]
    report = compare_runs(
        run(rows),
        run(rows, judge_config_hash="changed", cache_protocol="warm"),
        PROTOCOL,
    )
    assert report["protocol_compatible"] is False
    assert "protocol_mismatch:judge_config_hash" in report["ineligibility_reasons"]
    assert report["decision"] == "not_comparable"


def test_duplicate_result_identity_is_rejected_instead_of_best_selected():
    rows = [result("a", 0, 1), result("a", 0, 3)]
    with pytest.raises(ValueError, match="duplicate result identity"):
        compare_runs(run(rows), run(rows), PROTOCOL)


def test_bootstrap_is_deterministic_and_preserves_paired_clusters():
    baseline = run(
        [result(str(i), repeat, 1, 5) for i in range(8) for repeat in range(2)]
    )
    candidate = copy.deepcopy(baseline)
    for row in candidate["results"]:
        row["metrics"]["valid_question_yield"] = metric(
            2 + int(row["sample_id"]) % 2, 5
        )
    first = compare_runs(baseline, candidate, PROTOCOL)
    second = compare_runs(baseline, candidate, PROTOCOL)
    assert first == second
    assert first["metrics"]["valid_question_yield"]["ci95"][0] > 0
    assert first["decision"] == "exploratory"


def test_enough_reviewed_locked_clusters_can_support_primary_improvement():
    baseline = run(
        [result(str(i), repeat, 2, 5) for i in range(20) for repeat in range(2)]
    )
    candidate = run(
        [result(str(i), repeat, 3, 5) for i in range(20) for repeat in range(2)]
    )
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["comparison_eligible"] is True
    assert report["decision"] == "improved"
    assert report["metrics"]["valid_question_yield"]["degenerate"] is True


def test_noninferiority_margin_catches_secondary_regression():
    baseline = run(
        [
            result(str(i), repeat, 2, 5, source_support=metric(1))
            for i in range(20)
            for repeat in range(2)
        ]
    )
    candidate = run(
        [
            result(str(i), repeat, 3, 5, source_support=metric(0.95))
            for i in range(20)
            for repeat in range(2)
        ]
    )
    protocol = {
        **PROTOCOL,
        "noninferiority_metrics": {"source_support": {"margin": 0.02}},
    }
    report = compare_runs(baseline, candidate, protocol)
    assert report["decision"] == "inconclusive"
    assert report["noninferiority"]["source_support"]["pass"] is False


def test_cancelled_run_is_incomplete_even_with_saved_results():
    rows = [result("a", repeat, 3) for repeat in range(2)]
    candidate = run(rows)
    candidate["status"] = "cancelled"
    candidate["stop_reason"] = "budget_exceeded"
    report = compare_runs(run(rows), candidate, PROTOCOL)
    assert "run_incomplete" in report["ineligibility_reasons"]
    assert report["comparison_eligible"] is False


def test_missing_repeat_cannot_be_silently_dropped():
    baseline = run([result("a", repeat, 3) for repeat in range(2)])
    candidate = run([result("a", 0, 3)])
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert "planned_results_missing" in report["ineligibility_reasons"]


def test_hard_gate_failure_cannot_be_offset_by_better_yield():
    baseline = run(
        [
            result(str(i), repeat, 2, 5, authorization_safety=metric(1))
            for i in range(20)
            for repeat in range(2)
        ]
    )
    candidate = run(
        [
            result(str(i), repeat, 3, 5, authorization_safety=metric(0))
            for i in range(20)
            for repeat in range(2)
        ]
    )
    report = compare_runs(
        baseline,
        candidate,
        {**PROTOCOL, "hard_gates": {"authorization_safety": {"min": 1}}},
    )
    assert report["decision"] == "rejected_hard_gate"
    assert report["hard_gates"]["authorization_safety"]["pass"] is False


def test_single_review_provisional_gold_never_enables_formal_improvement():
    rows = [result(str(i), repeat, 2, 5) for i in range(20) for repeat in range(2)]
    report = compare_runs(
        run(rows, release_gold_status="provisional_single_review"),
        run(rows, release_gold_status="provisional_single_review"),
        PROTOCOL,
    )
    assert report["comparison_eligible"] is False
    assert "provisional_single_review_gold" in report["ineligibility_reasons"]


def test_independent_human_adjudication_can_resolve_unavailable_judge():
    rows = [result(str(i), repeat, 2, 5) for i in range(20) for repeat in range(2)]
    reviewed = run(rows, judge_calibrated=False, human_adjudication_complete=True)
    report = compare_runs(reviewed, reviewed, PROTOCOL)
    assert report["comparison_eligible"] is True


def test_frozen_similarity_cluster_map_controls_resampling():
    rows = [result(str(i), repeat, 2, 5) for i in range(20) for repeat in range(2)]
    copied = run(
        rows, sample_clusters={str(i): "one-connected-source-family" for i in range(20)}
    )
    report = compare_runs(copied, copied, PROTOCOL)
    assert report["cluster_count"] == 1
    assert report["comparison_eligible"] is False


def test_single_run_eligibility_reports_reasons_without_bootstrap():
    from rag_eval.comparison import assess_run

    rows = [result(str(i), repeat, 2, 5) for i in range(20) for repeat in range(2)]
    assert assess_run(run(rows), PROTOCOL)["comparison_eligible"] is True
    provisional = assess_run(
        run(rows, release_gold_status="provisional_single_review"), PROTOCOL
    )
    assert provisional["comparison_eligible"] is False
    assert "provisional_single_review_gold" in provisional["ineligibility_reasons"]


@pytest.fixture
def cost_pair():
    baseline = run(
        [result(str(i), repeat, 2, 5) for i in range(20) for repeat in range(2)]
    )
    candidate = run(
        [result(str(i), repeat, 3, 5) for i in range(20) for repeat in range(2)]
    )
    return baseline, candidate


@pytest.mark.parametrize("missing", [False, True])
def test_unknown_or_missing_candidate_cost_cannot_pass_the_budget(cost_pair, missing):
    baseline, candidate = cost_pair
    metrics = candidate["results"][0]["metrics"]
    if missing:
        metrics.pop("total_cost_cny")
    else:
        metrics["total_cost_cny"] = metric(
            0, unit="CNY", status="error", value=None, unknown_count=1
        )
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["cost_within_budget"] is None
    assert report["comparison_eligible"] is False
    assert report["decision"] == "exploratory"
    assert "candidate_cost_unknown" in report["ineligibility_reasons"]


def test_missing_frozen_cost_limit_is_not_replaced_by_a_comparison_override(cost_pair):
    baseline, candidate = cost_pair
    candidate["manifest"].pop("cost_estimate")
    report = compare_runs(
        baseline, candidate, {**PROTOCOL, "max_candidate_cost_cny": 1000}
    )
    assert report["cost_within_budget"] is None
    assert report["decision"] == "exploratory"
    assert "candidate_cost_limit_missing" in report["ineligibility_reasons"]


def test_frozen_candidate_limit_counts_all_repeats_and_cannot_be_raised(cost_pair):
    baseline, candidate = cost_pair
    candidate["manifest"]["cost_estimate"]["max_cost_cny"] = 0.3
    report = compare_runs(
        baseline, candidate, {**PROTOCOL, "max_candidate_cost_cny": 1000}
    )
    assert report["metrics"]["total_cost_cny"]["candidate"]["value"] == pytest.approx(
        0.4
    )
    assert report["cost_within_budget"] is False
    assert report["decision"] == "rejected_hard_gate"


def test_cost_at_frozen_limit_tolerates_float_representation_only(cost_pair):
    baseline, candidate = cost_pair
    candidate["manifest"]["cost_estimate"]["max_cost_cny"] = 0.4
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["cost_within_budget"] is True
    assert report["decision"] == "improved"


@pytest.mark.parametrize("invalid_limit", [None, True, -1, float("nan"), float("inf")])
def test_invalid_frozen_limit_is_exploratory(cost_pair, invalid_limit):
    baseline, candidate = cost_pair
    candidate["manifest"]["cost_estimate"]["max_cost_cny"] = invalid_limit
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["cost_within_budget"] is None
    assert report["decision"] == "exploratory"


def test_conflicting_immutable_sql_and_manifest_cost_limits_are_unconfirmed(cost_pair):
    baseline, candidate = cost_pair
    candidate["max_cost_cny"] = 2
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["cost_within_budget"] is None
    assert "candidate_cost_limit_mismatch" in report["ineligibility_reasons"]


def test_sql_limit_alone_is_a_supported_legacy_frozen_limit(cost_pair):
    baseline, candidate = cost_pair
    candidate["manifest"].pop("cost_estimate")
    candidate["max_cost_cny"] = 2
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["cost_within_budget"] is True
    assert report["decision"] == "improved"


def test_unknown_cost_protocol_never_silently_falls_back_to_legacy(cost_pair):
    baseline, candidate = cost_pair
    candidate["manifest"]["cost_protocol"] = {
        "version": "unrecognized",
        "currency": "CNY",
        "scope": "entire_run",
        "aggregation": "sum_all_attempts",
        "max_cost_cny": 100,
    }
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["cost_within_budget"] is None
    assert report["decision"] == "exploratory"


def test_single_run_unknown_cost_is_not_comparison_eligible(cost_pair):
    from rag_eval.comparison import assess_run

    _, candidate = cost_pair
    candidate["results"][0]["metrics"]["total_cost_cny"] = metric(
        0, unit="CNY", status="error", value=None, unknown_count=1
    )
    assert assess_run(candidate, PROTOCOL)["comparison_eligible"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"status": "na", "value": None},
        {"unit": "USD"},
        {"unknown_count": 1},
        {"value": None},
    ],
)
def test_unconfirmed_cost_measurement_never_passes(cost_pair, changes):
    baseline, candidate = cost_pair
    candidate["results"][0]["metrics"]["total_cost_cny"].update(changes)
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["cost_within_budget"] is None
    assert report["decision"] == "exploratory"


@pytest.mark.parametrize(
    "changes",
    [{"currency": "USD"}, {"scope": "selected_group"}, {"aggregation": "mean"}],
)
def test_unsupported_cost_protocol_cannot_establish_a_frozen_gate(cost_pair, changes):
    baseline, candidate = cost_pair
    candidate["manifest"]["cost_protocol"] = {
        "version": "run-cost-v1",
        "currency": "CNY",
        "scope": "entire_run",
        "aggregation": "sum_all_attempts",
        "max_cost_cny": 100,
        **changes,
    }
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["cost_within_budget"] is None
    assert report["decision"] == "exploratory"


def test_missing_result_outside_selected_group_keeps_run_cost_unknown(cost_pair):
    baseline, candidate = cost_pair
    for saved in (baseline, candidate):
        saved["cost_results"] = copy.deepcopy(saved["results"])
        saved["cost_planned_sample_ids"] = saved["manifest"]["planned_sample_ids"]
        saved["results"] = [row for row in saved["results"] if row["sample_id"] != "19"]
        saved["manifest"]["planned_sample_ids"] = [str(i) for i in range(19)]
    candidate["cost_results"] = [
        row for row in candidate["cost_results"] if row["sample_id"] != "19"
    ]
    report = compare_runs(baseline, candidate, {**PROTOCOL, "min_locked_clusters": 19})
    assert report["sample_count"] == 19
    assert report["cost_within_budget"] is None
    assert "candidate_cost_unknown" in report["ineligibility_reasons"]


def test_legacy_manifest_limit_matches_sql_at_its_storage_precision(cost_pair):
    baseline, candidate = cost_pair
    candidate["manifest"]["cost_estimate"]["max_cost_cny"] = 0.40000049
    candidate["max_cost_cny"] = 0.4
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["cost_within_budget"] is True
    assert report["decision"] == "improved"


def test_small_real_overspend_is_not_hidden_by_float_tolerance(cost_pair):
    baseline, candidate = cost_pair
    candidate["manifest"]["cost_estimate"]["max_cost_cny"] = 0.4
    candidate["results"][0]["metrics"]["total_cost_cny"] = metric(
        0.01000001, unit="CNY"
    )
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["cost_within_budget"] is False
    assert report["decision"] == "rejected_hard_gate"


def test_unknown_baseline_cost_prevents_formal_improvement(cost_pair):
    baseline, candidate = cost_pair
    baseline["results"][0]["metrics"].pop("total_cost_cny")
    report = compare_runs(baseline, candidate, PROTOCOL)
    assert report["cost_within_budget"] is True
    assert report["comparison_eligible"] is False
    assert report["decision"] == "exploratory"
    assert "baseline_cost_unknown" in report["ineligibility_reasons"]
