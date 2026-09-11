"""Paired request-preserving, connected-family cluster comparison.

Repeated executions first contribute their mean numerator and denominator within
one request. Cluster bootstrap resamples those requests together and recomputes
the original ratio. Neither questions nor repeats become independent samples.
"""

from __future__ import annotations

import math
import random
from copy import deepcopy
from collections import Counter, defaultdict
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .contracts import LEARNING_CASE_TYPES, LEARNING_METRIC_VERSION
from .metric_registry import CASE_TYPES, metric_applies

COST_PROTOCOL = {
    "version": "run-cost-v1",
    "currency": "CNY",
    "scope": "entire_run",
    "aggregation": "sum_all_attempts",
}

DEFAULT_PROTOCOL = {
    "protocol_version": "comparison-v1",
    "primary_metric": "context_evidence_group_recall",
    "required_metrics": [
        "context_evidence_group_recall",
        "answer_correctness",
        "source_support",
        "valid_question_yield",
        "full_set_pass",
    ],
    "noninferiority_metrics": {
        "source_support": {"margin": 0.02},
        "answer_correctness": {"margin": 0.02},
        "valid_question_yield": {"margin": 0.02},
        "full_set_pass": {"margin": 0.02},
    },
    "hard_gates": {
        "authorization_safety": {"min": 1},
        "production_isolation": {"min": 1},
        "revocation_safety": {"min": 1},
        "question_schema_pass": {"min": 1},
        "question_count_pass": {"min": 1},
        "citation_id_validity": {"min": 1},
        "citation_authorization": {"min": 1},
        "citation_hash_match": {"min": 1},
        "context_budget_pass": {"min": 1},
    },
    "bootstrap_iterations": 2000,
    "seed": 1729,
    "min_locked_clusters": 20,
    "compatibility_fields": [
        "dataset_hash",
        "annotation_version",
        "metric_version",
        "judge_config_hash",
        "cache_protocol",
        "context_token_budget",
        "split",
        "repeat_count",
    ],
}

PRACTICE_GENERATION_PROTOCOL = {
    **DEFAULT_PROTOCOL,
    "protocol_version": "practice-generation-comparison.v1",
    "primary_metric": "valid_question_yield",
    "required_metrics": [
        "practice_outcome_match",
        "valid_question_yield",
        "full_set_pass",
    ],
    "noninferiority_metrics": {},
    "hard_gates": {
        "practice_failure_behavior_match": {"min": 1},
        "practice_identity_match": {"min": 1},
        "question_schema_pass": {"min": 1},
        "question_count_pass": {"min": 1},
        "citation_id_validity": {"min": 1},
        "citation_authorization": {"min": 1},
        "citation_hash_match": {"min": 1},
        "citation_locator_match": {"min": 1},
        "context_budget_pass": {"min": 1},
    },
}
ANSWER_GRADING_PROTOCOL = {
    **DEFAULT_PROTOCOL,
    "protocol_version": "answer-grading-comparison.v1",
    "primary_metric": "grading_abs_error",
    "primary_higher_is_better": False,
    "required_metrics": ["grading_status_match", "grading_abs_error"],
    "noninferiority_metrics": {},
    "hard_gates": {
        "grading_failure_behavior_match": {"min": 1},
        "grading_identity_match": {"min": 1},
        "confirmation_policy_pass": {"min": 1},
        "citation_id_validity": {"min": 1},
        "citation_authorization": {"min": 1},
        "citation_hash_match": {"min": 1},
        "citation_locator_match": {"min": 1},
    },
}


def default_protocol(case_types) -> dict:
    """Select explicit metric gates; legacy four-case runs keep their protocol."""
    kinds = set(case_types)
    if not kinds <= CASE_TYPES:
        raise ValueError("unknown evaluation case_type")
    learning = kinds & LEARNING_CASE_TYPES
    if not learning:
        return deepcopy(DEFAULT_PROTOCOL)
    if learning == {"practice_generation"}:
        selected = PRACTICE_GENERATION_PROTOCOL
    elif learning == {"answer_grading"}:
        selected = ANSWER_GRADING_PROTOCOL
    else:
        selected = {
            **PRACTICE_GENERATION_PROTOCOL,
            "protocol_version": "learning-mvp-comparison.v1",
            "required_metrics": [
                *PRACTICE_GENERATION_PROTOCOL["required_metrics"],
                *ANSWER_GRADING_PROTOCOL["required_metrics"],
            ],
            "hard_gates": {
                **PRACTICE_GENERATION_PROTOCOL["hard_gates"],
                **ANSWER_GRADING_PROTOCOL["hard_gates"],
            },
        }
    if kinds - LEARNING_CASE_TYPES:
        # Mixed runs retain every applicable old hard gate, including policy.
        old_gates = {
            name: gate
            for name, gate in DEFAULT_PROTOCOL["hard_gates"].items()
            if any(metric_applies(name, kind) for kind in kinds - LEARNING_CASE_TYPES)
        }
        return deepcopy(
            {**selected, "hard_gates": {**old_gates, **selected["hard_gates"]}}
        )
    return deepcopy(selected)


def _protocol(runs: list[dict], supplied: dict | None) -> dict:
    if supplied is not None:
        config = {**DEFAULT_PROTOCOL, **supplied}
    else:
        saved = runs[0].get("manifest", {}).get("comparison_protocol")
        if saved is not None:
            if not isinstance(saved, dict):
                raise ValueError("comparison_protocol must be a JSON object")
            config = {**DEFAULT_PROTOCOL, **saved}
        else:
            config = default_protocol(
                row.get("case_type") for run in runs for row in run.get("results", [])
            )
    names = (
        set(config["required_metrics"])
        | {config["primary_metric"]}
        | set(config["noninferiority_metrics"])
        | set(config["hard_gates"])
    )
    for name in names:
        metric_applies(name, "retrieval")
    return config


def quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * probability
    low = math.floor(index)
    high = math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def _indexed(run: dict) -> dict[str, list[dict]]:
    result = defaultdict(list)
    seen = set()
    for row in run.get("results", []):
        sid, repeat = row.get("sample_id"), row.get("repeat_index", 0)
        if not isinstance(sid, str) or not sid or type(repeat) is not int or repeat < 0:
            raise ValueError("result requires sample_id and nonnegative repeat_index")
        if (sid, repeat) in seen:
            raise ValueError(f"duplicate result identity: {sid}, repeat {repeat}")
        seen.add((sid, repeat))
        kind = row.get("case_type")
        metric_applies("service_failure", kind)
        for name in row.get("metrics", {}):
            metric_applies(name, kind)
        cluster = run.get("manifest", {}).get("sample_clusters", {}).get(sid)
        result[sid].append(
            {**row, "cluster_id": cluster} if cluster is not None else row
        )
    return dict(result)


def _applies(name: str, row: dict) -> bool:
    return metric_applies(name, row.get("case_type"))


def _terms(index: dict, name: str, expected_repeats: int) -> tuple[dict, dict]:
    terms, counts = (
        {},
        {
            "ok_count": 0,
            "error_count": 0,
            "na_count": 0,
            "unknown_count": 0,
            "missing_count": 0,
        },
    )
    unit = "ratio"
    total_mode = name.endswith("_cost_cny") or name in {
        "provider_call_count",
        "unknown_call_count",
        "retry_count",
        "input_tokens",
        "output_tokens",
    }
    for sid, rows in index.items():
        relevant = [
            row for row in rows if _applies(name, row) or name in row.get("metrics", {})
        ]
        if not relevant:
            continue
        values = []
        for row in relevant:
            value = row.get("metrics", {}).get(name)
            if value is None:
                counts["missing_count"] += 1
                value = {
                    "status": "error",
                    "numerator": 0,
                    "denominator": 1,
                    "unknown_count": 1,
                }
            values.append(value)
        positive_denominators = [
            item.get("denominator", 0)
            for item in values
            if item.get("denominator", 0) > 0
        ]
        inferred_denominator = positive_denominators[0] if positive_denominators else 1
        for _ in range(max(0, expected_repeats - len(relevant))):
            counts["missing_count"] += 1
            values.append(
                {
                    "status": "error",
                    "numerator": 0,
                    "denominator": inferred_denominator,
                    "unknown_count": inferred_denominator,
                }
            )
        numerator = denominator = upper = scored_denominator = 0.0
        unknown_flag = False
        for item in values:
            status = item.get("status", "error")
            if status == "na":
                counts["na_count"] += 1
                continue
            if status not in {"ok", "error"}:
                raise ValueError("invalid metric status")
            counts[f"{status}_count"] += 1
            den = item.get("denominator", 1)
            num = item.get("numerator")
            if num is None:
                num = item.get("value", 0) or 0
                num *= den
            if not all(
                type(value) in (int, float) and math.isfinite(value) and value >= 0
                for value in (num, den)
            ):
                raise ValueError("metric counts must be finite and nonnegative")
            unit = item.get("unit", unit)
            # Ranking proportions aggregate per query, not by ideal DCG magnitude.
            if name.startswith(("mrr@", "ndcg@")) and den:
                num, den = num / den, 1
            details = item.get("details", {})
            unknown = item.get("unknown_count", 0) if status == "error" else 0
            counts["unknown_count"] += unknown
            unknown_flag |= status == "error"
            numerator += num
            denominator += den
            upper += (
                den * details["upper_bound"]
                if details.get("upper_bound") is not None
                else min(den, num + unknown)
                if unit == "ratio"
                else num
            )
            scored_denominator += (
                details.get("scored_denominator", max(0, den - unknown))
                if status == "error"
                else den
            )
        repeat_divisor = (
            1
            if total_mode or name == "cost_per_valid_question_cny"
            else max(1, len(values))
        )
        terms[sid] = {
            "n": numerator / repeat_divisor,
            "d": denominator / repeat_divisor,
            "u": upper / repeat_divisor,
            "s": scored_denominator / repeat_divisor,
            "error": unknown_flag,
        }
    return terms, {**counts, "unit": unit, "total_mode": total_mode}


def _aggregate(terms: dict, counts: dict) -> dict:
    numerator = sum(item["n"] for item in terms.values())
    denominator = sum(item["d"] for item in terms.values())
    upper = sum(item["u"] for item in terms.values())
    scored = sum(item["s"] for item in terms.values())
    error = any(item["error"] for item in terms.values())
    value_den = 1 if counts["total_mode"] and denominator else denominator
    status = "error" if error else "ok" if denominator else "na"
    return {
        "status": status,
        "value": numerator / value_den if value_den and not error else None,
        "numerator": numerator,
        "denominator": value_den,
        "unit": counts["unit"],
        "conditional_value": numerator / scored if scored else None,
        "lower_bound": numerator / value_den if value_den else None,
        "upper_bound": upper / value_den if value_den else None,
        "scoring_coverage": scored / denominator if denominator else None,
        "request_count": len(terms),
        **{
            key: value
            for key, value in counts.items()
            if key not in {"unit", "total_mode"}
        },
    }


def _clusters(
    indexes: list[dict], paired_ids: list[str]
) -> tuple[dict, int, bool, bool]:
    parent, families_by_sample, splits_by_sample = {}, {}, defaultdict(set)
    missing_family = False

    def find(item):
        parent.setdefault(item, item)
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left, right):
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    real_families = set()
    for sid in paired_ids:
        families = set()
        for index in indexes:
            for row in index[sid]:
                family_ids = row.get("family_ids") or (
                    [row["family_id"]] if row.get("family_id") else []
                )
                if family_ids:
                    families.update(family_ids)
                    real_families.update(family_ids)
                if row.get("cluster_id"):
                    families.add(f"declared-cluster:{row['cluster_id']}")
                if row.get("split"):
                    splits_by_sample[sid].add(row["split"])
        if not families:
            missing_family = True
            families.add(f"unknown:{sid}")
        families_by_sample[sid] = sorted(families)
        first = min(families)
        for family in families:
            union(first, family)
    clusters, cluster_splits = defaultdict(list), defaultdict(set)
    for sid, families in families_by_sample.items():
        cluster = find(families[0])
        clusters[cluster].append(sid)
        cluster_splits[cluster].update(splits_by_sample[sid])
    return (
        dict(sorted(clusters.items())),
        len(real_families),
        any(len(splits) > 1 for splits in cluster_splits.values()),
        missing_family,
    )


def _cluster_terms(terms: dict, clusters: dict) -> list[tuple[float, float]]:
    return [
        (
            sum(terms.get(sid, {}).get("n", 0) for sid in ids),
            sum(terms.get(sid, {}).get("d", 0) for sid in ids),
        )
        for ids in clusters.values()
    ]


def _bootstrap(
    left: list, right: list, iterations: int, seed: int, total_mode: bool
) -> list[float]:
    rng = random.Random(seed)
    values = []
    for _ in range(iterations):
        draws = Counter(rng.randrange(len(left)) for _ in left)
        an = sum(left[index][0] * count for index, count in draws.items())
        ad = sum(left[index][1] * count for index, count in draws.items())
        bn = sum(right[index][0] * count for index, count in draws.items())
        bd = sum(right[index][1] * count for index, count in draws.items())
        if ad and bd:
            values.append(bn - an if total_mode else bn / bd - an / ad)
    return values


def _complete(run: dict, index: dict) -> bool:
    return (
        run.get("status", run.get("manifest", {}).get("status")) == "completed"
        and not run.get("stop_reason")
        and all(
            row.get("status", "completed")
            in {"completed", "failed", "refused", "scored"}
            for rows in index.values()
            for row in rows
        )
    )


def _run_reasons(run: dict, index: dict, config: dict) -> set[str]:
    manifest, reasons = run.get("manifest", {}), set()
    if (
        manifest.get("raw_artifacts_status") == "expired"
        or manifest.get("reproducible") is False
    ):
        reasons.add("raw_artifacts_expired")
    if not _complete(run, index):
        reasons.add("run_incomplete")
    repeats = manifest.get("repeat_count", 1)
    if type(repeats) is not int or not 1 <= repeats <= 100:
        raise ValueError("repeat_count must be a positive bounded integer")
    if set(manifest.get("planned_sample_ids", sorted(index))) != set(index) or any(
        {row["repeat_index"] for row in rows} != set(range(repeats))
        for rows in index.values()
    ):
        reasons.add("planned_results_missing")
    if (
        manifest.get("dataset_state") != "frozen"
        or manifest.get("gold_reviewed") is not True
    ):
        reasons.add("gold_not_frozen_and_human_reviewed")
    if (
        manifest.get("release_gold_status") == "provisional_single_review"
        or manifest.get("formal_gold_eligible") is False
    ):
        reasons.add("provisional_single_review_gold")
    if (
        manifest.get("judge_calibrated") is not True
        and manifest.get("human_adjudication_complete") is not True
    ):
        reasons.add("judge_not_calibrated")
    if manifest.get("split") != "locked_test":
        reasons.add("not_locked_test")
    if manifest.get("protocol_frozen") is not True:
        reasons.add("protocol_not_frozen")
    learning = any(
        row.get("case_type") in LEARNING_CASE_TYPES
        for rows in index.values()
        for row in rows
    )
    if learning and manifest.get("metric_version") != LEARNING_METRIC_VERSION:
        reasons.add("protocol_mismatch:metric_version")
    saved_protocol = manifest.get("comparison_protocol", {})
    if not isinstance(saved_protocol, dict):
        raise ValueError("comparison_protocol must be a JSON object")
    saved_version = manifest.get(
        "protocol_version", saved_protocol.get("protocol_version")
    )
    if (learning or saved_version is not None) and saved_version != config[
        "protocol_version"
    ]:
        reasons.add("protocol_mismatch:protocol_version")
    if (
        saved_protocol
        and saved_protocol.get("protocol_version") != config["protocol_version"]
    ):
        reasons.add("protocol_mismatch:protocol_version")
    if saved_protocol and any(
        config.get(key) != value for key, value in saved_protocol.items()
    ):
        reasons.add("protocol_mismatch:comparison_protocol")
    return reasons


def _frozen_cost_limit(run: dict) -> tuple[float | None, set[str], list[str]]:
    """Resolve saved ceilings; comparison-time options cannot replace them."""
    manifest = run.get("manifest", {})
    reasons, sources = set(), {}
    if manifest.get("protocol_frozen") is not True:
        reasons.add("cost_protocol_not_frozen")
    if "cost_protocol" in manifest:
        protocol = manifest["cost_protocol"]
        if not isinstance(protocol, dict) or any(
            protocol.get(key) != value for key, value in COST_PROTOCOL.items()
        ):
            reasons.add("cost_protocol_unrecognized")
        else:
            sources["manifest.cost_protocol"] = protocol.get("max_cost_cny")
    if "cost_estimate" in manifest:
        estimate = manifest["cost_estimate"]
        if (
            not isinstance(estimate, dict)
            or estimate.get("kind", "conservative_ceiling") != "conservative_ceiling"
        ):
            reasons.add("cost_protocol_unrecognized")
        else:
            sources["manifest.cost_estimate"] = estimate.get("max_cost_cny")
    if "max_cost_cny" in run:
        sources["run.max_cost_cny"] = run["max_cost_cny"]
    if not sources:
        reasons.add("cost_limit_missing")
    limits = {}
    for source, value in sources.items():
        if type(value) not in (int, float, Decimal):
            reasons.add("cost_limit_invalid")
            continue
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            reasons.add("cost_limit_invalid")
            continue
        limits[source] = amount
    limit = None
    if limits and not reasons:
        # MySQL persists the immutable ceiling as DECIMAL(18,6). Legacy JSON
        # retained the request's precision, so compare snapshots at that scale.
        if "run.max_cost_cny" in limits:
            try:
                rounded = {
                    amount.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
                    for amount in limits.values()
                }
            except InvalidOperation:
                reasons.add("cost_limit_invalid")
            else:
                if len(rounded) != 1:
                    reasons.add("cost_limit_mismatch")
            limit = float(limits["run.max_cost_cny"])
        else:
            if len(set(limits.values())) != 1:
                reasons.add("cost_limit_mismatch")
            limit = float(next(iter(limits.values())))
        if not math.isfinite(limit):
            reasons.add("cost_limit_invalid")
    return None if reasons else limit, reasons, sorted(sources)


def _cost_gate(run: dict) -> dict:
    """Keep run-wide cost independent of paired samples and UI group filters."""
    limit, reasons, sources = _frozen_cost_limit(run)
    manifest = run.get("manifest", {})
    index = _indexed({"results": run.get("cost_results", run.get("results", []))})
    planned = run.get("cost_planned_sample_ids", manifest.get("planned_sample_ids"))
    repeats = manifest.get("repeat_count", 1)
    complete = (
        bool(index)
        and isinstance(planned, list)
        and all(isinstance(sid, str) for sid in planned)
        and len(planned) == len(set(planned))
        and set(planned) == set(index)
        and all(
            {row["repeat_index"] for row in rows} == set(range(repeats))
            for rows in index.values()
        )
        and _complete(run, index)
    )
    costs, known_parts = [], []
    unknown = 0
    for rows in index.values():
        for row in rows:
            metric = row.get("metrics", {}).get("total_cost_cny") or {}
            value = metric.get("value")
            details = metric.get("details") or {}
            known = (
                metric.get("status") == "ok"
                and metric.get("unit") == "CNY"
                and metric.get("unknown_count", 0) == 0
                and type(value) in (int, float)
                and math.isfinite(value)
                and value >= 0
                and metric.get("denominator", 1) == 1
                and details.get("aggregation", "sum_all_attempts") == "sum_all_attempts"
                and details.get("cost_status") != "unknown"
            )
            if known:
                costs.append(value)
                known_parts.append(value)
            else:
                unknown += 1
                subtotal = details.get("known_cost_cny", metric.get("numerator"))
                if (
                    metric.get("unit") == "CNY"
                    and type(subtotal) in (int, float)
                    and math.isfinite(subtotal)
                    and subtotal >= 0
                ):
                    known_parts.append(subtotal)
    total = math.fsum(costs) if complete and not unknown else None
    if total is None:
        reasons.add("cost_unknown")
    passed = None
    if not reasons:
        # Allow representation noise only, without rounding away real overspend.
        passed = total <= limit or math.isclose(
            total, limit, rel_tol=0, abs_tol=4 * math.ulp(limit)
        )
    return {
        "pass": passed,
        "scope": "entire_run",
        "currency": "CNY",
        "aggregation": "sum_all_attempts",
        "max_cost_cny": limit,
        "total_cost_cny": total,
        "known_cost_cny": math.fsum(known_parts),
        "unknown_result_count": unknown,
        "results_complete": bool(complete),
        "limit_sources": sources,
        "ineligibility_reasons": sorted(reasons),
    }


def assess_run(run: dict, protocol: dict | None = None) -> dict:
    """Check a single run's comparison prerequisites without running bootstrap.

    True means the run can enter a compatible comparison, not that the candidate
    improved or passed the release hard gates.
    """
    config = _protocol([run], protocol)
    index = _indexed(run)
    reasons = _run_reasons(run, index, config)
    clusters, families, split_leakage, missing_family = _clusters(
        [index], sorted(index)
    )
    if split_leakage:
        reasons.add("connected_cluster_split_leakage")
    if missing_family:
        reasons.add("family_or_cluster_identity_missing")
    if len(clusters) < config["min_locked_clusters"]:
        reasons.add("insufficient_independent_locked_clusters")
    if not index:
        reasons.add("no_paired_samples")
    required = (
        set(config["required_metrics"])
        | {config["primary_metric"]}
        | set(config["noninferiority_metrics"])
        | set(config["hard_gates"])
    )
    for name in required:
        terms, counts = _terms(
            index, name, run.get("manifest", {}).get("repeat_count", 1)
        )
        if _aggregate(terms, counts)["status"] != "ok":
            reasons.add("unresolved_core_metrics")
    cost_gate = _cost_gate(run)
    reasons.update(cost_gate["ineligibility_reasons"])
    return {
        "comparison_eligible": not reasons,
        "ineligibility_reasons": sorted(reasons),
        "sample_count": len(index),
        "cluster_count": len(clusters),
        "family_count": families,
        "cost_within_budget": cost_gate["pass"],
        "cost_gate": cost_gate,
    }


def compare_runs(baseline: dict, candidate: dict, protocol: dict | None = None) -> dict:
    """Compare saved final outputs; never reruns generation or selects best attempts."""
    config = _protocol([baseline, candidate], protocol)
    iterations, seed = config["bootstrap_iterations"], config["seed"]
    if (
        type(iterations) is not int
        or not 100 <= iterations <= 100000
        or type(seed) is not int
    ):
        raise ValueError("bootstrap needs 100..100000 iterations and an integer seed")
    left, right = _indexed(baseline), _indexed(candidate)
    lm, rm = baseline.get("manifest", {}), candidate.get("manifest", {})
    paired_ids = sorted(set(left) & set(right))
    reasons = set()
    compatible = True
    for key in set(config["compatibility_fields"]) | {"metric_version"}:
        if key not in lm or key not in rm or lm[key] != rm[key]:
            reasons.add(f"protocol_mismatch:{key}")
            compatible = False
    if set(left) != set(right):
        reasons.add("sample_id_mismatch")
        compatible = False
    for run, index in ((baseline, left), (candidate, right)):
        reasons.update(_run_reasons(run, index, config))
    if any(reason.startswith("protocol_mismatch:") for reason in reasons):
        compatible = False
    if any("protocol_version" in manifest for manifest in (lm, rm)) and lm.get(
        "protocol_version"
    ) != rm.get("protocol_version"):
        reasons.add("protocol_mismatch:protocol_version")
        compatible = False
    if any("comparison_protocol" in manifest for manifest in (lm, rm)) and lm.get(
        "comparison_protocol"
    ) != rm.get("comparison_protocol"):
        reasons.add("protocol_mismatch:comparison_protocol")
        compatible = False
    if any(
        {row.get("case_type") for row in left[sid]}
        != {row.get("case_type") for row in right[sid]}
        for sid in paired_ids
    ):
        reasons.add("sample_case_type_mismatch")
        compatible = False
    paired_left, paired_right = (
        {sid: left[sid] for sid in paired_ids},
        {sid: right[sid] for sid in paired_ids},
    )
    clusters, family_count, split_leakage, missing_family = _clusters(
        [paired_left, paired_right], paired_ids
    )
    if split_leakage:
        reasons.add("connected_cluster_split_leakage")
    if missing_family:
        reasons.add("family_or_cluster_identity_missing")
    if len(clusters) < config["min_locked_clusters"]:
        reasons.add("insufficient_independent_locked_clusters")
    if not paired_ids:
        reasons.add("no_paired_samples")
    metric_names = (
        set(config["required_metrics"])
        | {config["primary_metric"]}
        | set(config["noninferiority_metrics"])
        | set(config["hard_gates"])
    )
    metric_names.update(
        name
        for index in (paired_left, paired_right)
        for rows in index.values()
        for row in rows
        for name in row.get("metrics", {})
    )
    reports = {}
    for name in sorted(metric_names):
        at, ac = _terms(paired_left, name, lm.get("repeat_count", 1))
        bt, bc = _terms(paired_right, name, rm.get("repeat_count", 1))
        a, b = _aggregate(at, ac), _aggregate(bt, bc)
        delta = (
            b["value"] - a["value"]
            if a["value"] is not None and b["value"] is not None
            else None
        )
        boot = (
            _bootstrap(
                _cluster_terms(at, clusters),
                _cluster_terms(bt, clusters),
                iterations,
                seed,
                ac["total_mode"],
            )
            if delta is not None and clusters
            else []
        )
        interval = [quantile(boot, 0.025), quantile(boot, 0.975)] if boot else None
        reports[name] = {
            "baseline": a,
            "candidate": b,
            "delta": delta,
            "delta_percentage_points": delta * 100
            if delta is not None and ac["unit"] == "ratio"
            else None,
            "ci95": interval,
            "degenerate": bool(boot and max(boot) - min(boot) < 1e-12),
            "bootstrap_valid_resamples": len(boot),
        }
    required = (
        set(config["required_metrics"])
        | {config["primary_metric"]}
        | set(config["noninferiority_metrics"])
        | set(config["hard_gates"])
    )
    if any(
        reports[name][side]["status"] != "ok"
        for name in required
        for side in ("baseline", "candidate")
    ):
        reasons.add("unresolved_core_metrics")
    hard_gates = {}
    for name, gate in config["hard_gates"].items():
        result = reports[name]["candidate"]
        value = result["value"]
        passed = (
            None
            if value is None
            else (
                value >= gate.get("min", -math.inf)
                and value <= gate.get("max", math.inf)
            )
        )
        hard_gates[name] = {"pass": passed, "value": value, "threshold": gate}
    noninferiority = {}
    for name, rule in config["noninferiority_metrics"].items():
        rule = {"margin": rule} if isinstance(rule, (int, float)) else rule
        interval = reports[name]["ci95"]
        benefit_lower = (
            None
            if interval is None
            else interval[0]
            if rule.get("higher_is_better", True)
            else -interval[1]
        )
        noninferiority[name] = {
            "margin": rule.get("margin", 0.02),
            "benefit_ci_lower": benefit_lower,
            "pass": None
            if benefit_lower is None
            else benefit_lower >= -rule.get("margin", 0.02),
        }
    candidate_cost_gate = _cost_gate(candidate)
    baseline_cost_gate = _cost_gate(baseline)
    for label, gate in (
        ("baseline", baseline_cost_gate),
        ("candidate", candidate_cost_gate),
    ):
        reasons.update(f"{label}_{reason}" for reason in gate["ineligibility_reasons"])
    cost_pass = candidate_cost_gate["pass"]
    eligible = not reasons
    primary = reports[config["primary_metric"]]
    primary_ci = primary["ci95"]
    primary_lower = (
        None
        if primary_ci is None
        else primary_ci[0]
        if config.get("primary_higher_is_better", True)
        else -primary_ci[1]
    )
    hard_failed = (
        any(item["pass"] is False for item in hard_gates.values()) or cost_pass is False
    )
    if not compatible:
        decision = "not_comparable"
    elif hard_failed:
        decision = "rejected_hard_gate"
    elif not eligible:
        decision = "exploratory"
    elif (
        primary_lower is not None
        and primary_lower > 0
        and all(item["pass"] is True for item in noninferiority.values())
    ):
        decision = "improved"
    else:
        decision = "inconclusive"
    engineering = {}
    for name in sorted(metric_names):
        if name.endswith("_latency_ms"):
            engineering[name] = {}
            for label, index in (("baseline", left), ("candidate", right)):
                values = [
                    row["metrics"][name]["value"]
                    for rows in index.values()
                    for row in rows
                    if row.get("metrics", {}).get(name, {}).get("status") == "ok"
                ]
                engineering[name][label] = {
                    "count": len(values),
                    "p50": quantile(values, 0.5),
                    "p95": quantile(values, 0.95),
                }
    return {
        "protocol_version": config["protocol_version"],
        "protocol_compatible": compatible,
        "comparison_eligible": eligible,
        "provisional": not eligible,
        "decision": decision,
        "ineligibility_reasons": sorted(reasons),
        "sample_count": len(paired_ids),
        "family_count": family_count,
        "cluster_count": len(clusters),
        "repeat_count": lm.get("repeat_count"),
        "unpaired_baseline_count": len(set(left) - set(right)),
        "unpaired_candidate_count": len(set(right) - set(left)),
        "clusters": clusters,
        "bootstrap": {
            "iterations": iterations,
            "seed": seed,
            "unit": "connected_document_family_cluster",
            "paired": True,
        },
        "primary_metric": config["primary_metric"],
        "metrics": reports,
        "hard_gates": hard_gates,
        "noninferiority": noninferiority,
        "cost_within_budget": cost_pass,
        "cost_gate": candidate_cost_gate,
        "engineering": engineering,
        "limitations": [
            "Intervals are conditional on saved gold and judge decisions; they exclude systematic judge and annotation error.",
            "Degenerate intervals or zero observed errors do not establish zero future risk.",
            "Fewer than the prescribed locked-test clusters cannot establish a formal improvement claim.",
        ],
        "aggregation": "mean_repeats_within_request_then_recompute_original_ratio; all_attempt_costs_sum",
    }
