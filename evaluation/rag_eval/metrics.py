"""Deterministic metrics. Inputs and outputs are JSON; no provider or backend I/O."""

from __future__ import annotations

import math
import re
from decimal import Decimal, DecimalException

from .contracts import (
    LEARNING_METRIC_VERSION,
    metric,
    metric_config,
    not_applicable,
    uncertain,
    validate_pair,
)
from .evidence import candidates_of, context_of, coverage, redundancy
from .metric_registry import CONTEXT_CASES, metric_applies
from .normalization import normalize_artifact
from .ranking import ranking_metrics

_AMOUNT = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


def _amount(value, *, allow_string=False) -> float | None:
    if allow_string and isinstance(value, str) and _AMOUNT.fullmatch(value):
        try:
            exact = Decimal(value)
            number = float(exact)
            if exact.is_finite() and exact >= 0 and math.isfinite(number):
                return number if not exact or number > 0 else None
        except (DecimalException, OverflowError):
            pass
    if type(value) in (int, float) and math.isfinite(value) and value >= 0:
        return value
    return None


def _personal_cost_na(version: str, *, unit="CNY") -> dict:
    return metric(
        None, 0, version=version, unit=unit, status="na",
        reason="personal_model_not_platform_billed",
        details={"cost_status": "not_applicable", "aggregation": "system_calls_only"},
    )


def _reservation_metrics(usage: dict, calls: list, missing: bool, version: str) -> dict:
    system_calls = [call for call in calls if call.get("config_source") != "user"]
    if calls and not system_calls and not missing:
        return {
            name: _personal_cost_na(version)
            for name in ("reserved_cost_cny", "unknown_reserved_cost_cny")
        }
    personal_calls = [call for call in calls if call.get("config_source") == "user"]
    source_aware_totals = not personal_calls or (
        usage.get("cost_status_cny") in {"estimated", "unknown"}
        and all(
            call.get("cost_status") == "not_applicable"
            and call.get("cost_cny") is None
            and call.get("reserved_cost_cny") is None
            for call in personal_calls
        )
    )
    calls = system_calls
    output = {}
    for name, selected in (
        ("reserved_cost_cny", calls),
        (
            "unknown_reserved_cost_cny",
            [
                call
                for call in calls
                if call.get("status") in {"reserved", "unknown"}
                or call.get("cost_status") == "unknown"
            ],
        ),
    ):
        if name in usage and source_aware_totals:
            value = _amount(usage[name], allow_string=True)
            unknown = int(value is None) + int(missing)
            total = value or 0
        else:
            values = [
                _amount(call.get("reserved_cost_cny"), allow_string=True)
                for call in selected
            ]
            total = sum(value for value in values if value is not None)
            unknown = sum(value is None for value in values) + int(missing)
        output[name] = metric(
            total,
            version=version,
            unit="CNY",
            status="error" if unknown else "ok",
            unknown=unknown,
            reason="reservation_unreported" if unknown else None,
            details={
                "known_reserved_cost_cny": total,
                "aggregation": "sum_all_attempts",
            },
        )
    return output


def coverage_metrics(sample: dict, artifact: dict, config: dict) -> dict:
    groups = sample.get("gold_evidence_groups", [])
    candidates, context = candidates_of(artifact), context_of(artifact)
    version = config["metric_version"]
    output = {}
    sets = [(f"@{k}", candidates[:k]) for k in config.get("retrieval_ks", [5, 10, 20])]
    sets.append(("context", context))
    if sample.get("expected_outcome") == "unanswerable":
        groups = []
    hits_by_set = {}
    for suffix, evidence in sets:
        recall_name = (
            "context_evidence_group_recall"
            if suffix == "context"
            else f"evidence_group_recall{suffix}"
        )
        all_name = (
            "context_all_evidence" if suffix == "context" else f"all_evidence{suffix}"
        )
        if not groups:
            output[recall_name] = not_applicable(
                "no_gold_evidence_groups", version=version
            )
            output[all_name] = not_applicable(
                "no_gold_evidence_groups", version=version
            )
            continue
        hit, unknown = coverage(
            groups, evidence, sample, artifact.get("mapping_status") == "mapping_failed"
        )
        hits_by_set[suffix] = len(hit)
        details = {
            "hit_group_ids": hit,
            "unknown_group_ids": unknown,
            "candidate_count": len(evidence),
            "cutoff_unit": "retrieval_candidates"
            if suffix != "context"
            else "final_context",
            "coverage_rule": "complete_union_of_unicode_codepoint_ranges",
        }
        if unknown:
            output[recall_name] = uncertain(
                len(hit),
                len(groups),
                len(unknown),
                "mapping_failed",
                version=version,
                **details,
            )
            known_miss = len(groups) - len(hit) - len(unknown)
            output[all_name] = (
                metric(0, version=version, details=details)
                if known_miss
                else uncertain(0, 1, 1, "mapping_failed", version=version, **details)
            )
        else:
            output[recall_name] = metric(
                len(hit), len(groups), version=version, details=details
            )
            output[all_name] = metric(
                int(len(hit) == len(groups)), version=version, details=details
            )
    duplicate, total = redundancy(context, sample)
    output["context_redundancy"] = metric(
        duplicate, total, version=version, details={"unit": "source_characters"}
    )
    before, _ = coverage(groups, candidates, sample) if groups else ([], [])
    after = hits_by_set.get("context", 0)
    output["evidence_retention"] = metric(after, len(before), version=version)
    tokens = artifact.get("usage", {}).get(
        "context_tokens", artifact.get("evidence_pack", {}).get("context_tokens")
    )
    if type(tokens) is int and tokens >= 0:
        output["context_tokens"] = metric(tokens, unit="tokens", version=version)
        output["context_budget_pass"] = metric(
            int(tokens <= config.get("context_token_budget", 6000)), version=version
        )
    else:
        output["context_tokens"] = uncertain(
            0, 1, 1, "context_tokens_unreported", version=version
        )
        output["context_budget_pass"] = uncertain(
            0, 1, 1, "context_tokens_unreported", version=version
        )
    output["candidate_count"] = metric(len(candidates), unit="count", version=version)
    output.update(ranking_metrics(sample, candidates, config))
    return output


def cost_metrics(
    artifact: dict,
    config: dict,
    confirmed_valid: int | None = None,
    *,
    validity: dict | None = None,
) -> dict:
    version = config["metric_version"]
    learning = version == LEARNING_METRIC_VERSION
    usage = artifact.get("usage", {})
    ledger_missing = "calls" not in usage or usage.get("ledger_complete") is False
    seen, calls = {}, []
    for i, call in enumerate(usage.get("calls", [])):
        key = (call.get("call_id", f"missing-id-{i}"), call.get("attempt", 1))
        if key in seen:
            if seen[key] != call:
                raise ValueError(
                    "conflicting cost ledger entries for the same call attempt"
                )
            continue
        seen[key] = call
        calls.append(call)
    personal_calls = [call for call in calls if call.get("config_source") == "user"]
    totals, unknowns, personal_stages, billable_stages = {}, {}, set(), set()
    estimated = 0
    for call in calls:
        stage = call.get("stage", "unknown")
        stage = "rerank" if stage == "llm" and call.get("purpose") == "reranker" else {
            "llm": "generation", "reranker": "rerank"
        }.get(stage, stage)
        metric_applies(f"{stage}_cost_cny", artifact.get("case_type", "retrieval"))
        if call.get("config_source") == "user":
            personal_stages.update(("total", stage))
            continue
        billable_stages.update(("total", stage))
        cost = _amount(call.get("cost_cny"), allow_string=learning)
        known = cost is not None and call.get("cost_status") in {
            "actual",
            "estimated",
            "provider_reported",
        }
        for name in ("total", stage):
            totals[name] = totals.get(name, 0) + (cost if known else 0)
            unknowns[name] = unknowns.get(name, 0) + int(not known)
        estimated += int(call.get("cost_status") == "estimated")
    personal_only = bool(personal_calls) and len(personal_calls) == len(calls)
    output = {}
    for stage in {
        "total",
        "generation",
        "judge",
        "index",
        "retrieval",
        "rerank",
        *totals,
        *personal_stages,
    }:
        if not ledger_missing and (
            personal_only or stage in personal_stages and stage not in billable_stages
        ):
            output[f"{stage}_cost_cny"] = _personal_cost_na(version)
            continue
        value, unknown = (
            totals.get(stage, 0),
            unknowns.get(stage, 0) + int(ledger_missing),
        )
        details = {
            "cost_status": "unknown"
            if unknown
            else "estimated"
            if estimated
            else "actual",
            "estimated_call_count": estimated,
            "known_cost_cny": value,
            "aggregation": "sum_all_attempts",
        }
        output[f"{stage}_cost_cny"] = metric(
            value,
            version=version,
            unit="CNY",
            status="error" if unknown else "ok",
            unknown=unknown,
            reason="call_ledger_unreported"
            if ledger_missing
            else "unknown_provider_cost"
            if unknown
            else None,
            details=details,
        )
    ledger_unknown = int(learning and ledger_missing)
    ledger_state = {
        "status": "error" if ledger_unknown else "ok",
        "unknown": ledger_unknown,
        "reason": "call_ledger_unreported" if ledger_unknown else None,
    }
    output["provider_call_count"] = metric(
        len(calls), unit="count", version=version, **ledger_state
    )
    output["retry_count"] = metric(
        sum(call.get("attempt", 1) > 1 for call in calls),
        unit="count",
        version=version,
        **ledger_state,
    )
    output["provider_error_rate"] = metric(
        sum(
            call.get("status") in {"failed", "error", "timeout"}
            or call.get("status") == "unknown" and bool(call.get("error_code") or call.get("error_type"))
            for call in calls
        ),
        max(1, len(calls)) if ledger_unknown else len(calls),
        version=version,
        **ledger_state,
    )
    for token_name in ("input_tokens", "output_tokens"):
        known = [
            call[token_name]
            for call in calls
            if type(call.get(token_name)) is int and call[token_name] >= 0
        ]
        missing = len(calls) - len(known) + ledger_unknown
        output[token_name] = metric(
            sum(known),
            unit="tokens",
            version=version,
            status="error" if missing else "ok",
            reason="provider_usage_unreported" if missing else None,
            unknown=missing,
        )
    for stage, value in usage.get("stages_ms", usage.get("stage_ms", {})).items():
        name = f"{stage}_latency_ms"
        if not metric_applies(name, artifact.get("case_type", "retrieval")):
            raise ValueError(f"metric {name!r} does not apply to this case_type")
        if type(value) in (int, float) and math.isfinite(value) and value >= 0:
            output[name] = metric(
                value,
                unit="ms",
                version=version,
                details={"aggregation": "distribution"},
            )
        elif learning:
            output[name] = metric(
                None,
                version=version,
                unit="ms",
                status="error",
                unknown=1,
                reason="stage_latency_unreported",
            )
    if learning:
        output.update(_reservation_metrics(usage, calls, ledger_missing, version))
        declared_unknown = usage.get("unknown_call_count", 0)
        if type(declared_unknown) is not int or declared_unknown < 0:
            raise ValueError("unknown_call_count must be a nonnegative integer")
        if personal_calls:
            declared_unknown = unknowns.get("total", 0)
        output["unknown_call_count"] = metric(
            max(declared_unknown, unknowns.get("total", 0)),
            unit="count",
            version=version,
            **ledger_state,
        )
    if learning and validity is not None and validity.get("status") == "error":
        output["cost_per_valid_question_cny"] = metric(
            None,
            version=version,
            unit="CNY/question",
            status="error",
            unknown=1,
            reason="valid_question_count_unresolved",
            details={
                "denominator_kind": "confirmed_valid_questions",
                "denominator_known": False,
            },
        )
    elif confirmed_valid is not None:
        if personal_only and not ledger_missing:
            output["cost_per_valid_question_cny"] = _personal_cost_na(
                version, unit="CNY/question"
            )
        elif confirmed_valid == 0:
            output["cost_per_valid_question_cny"] = metric(
                None, 0, status="na", reason="no_confirmed_valid_output",
                version=version, unit="CNY/question",
            )
        else:
            output["cost_per_valid_question_cny"] = metric(
                totals.get("total", 0),
                confirmed_valid,
                version=version,
                unit="CNY/question",
                status="error" if unknowns.get("total", 0) or ledger_missing else "ok",
                reason="call_ledger_unreported"
                if ledger_missing
                else "unknown_provider_cost"
                if unknowns.get("total", 0)
                else None,
                unknown=unknowns.get("total", 0) + int(ledger_missing),
                details={"denominator_kind": "confirmed_valid_questions"},
            )
    return output


def policy_metrics(sample: dict, artifact: dict, config: dict) -> dict:
    version = config["metric_version"]
    observations = artifact.get("observations", {})
    output = {}
    for name, field in (
        ("authorization_safety", "unauthorized_source_count"),
        ("production_isolation", "production_side_effect_count"),
        ("revocation_safety", "stale_publish_count"),
    ):
        value = observations.get(field)
        output[name] = (
            metric(
                int(value == 0),
                version=version,
                details={"observed_violations": value, "hard_gate": True},
            )
            if type(value) is int and value >= 0
            else uncertain(0, 1, 1, "policy_observation_missing", version=version)
        )
    expected = sample.get("expected_status")
    expected_error = sample.get("expected_error_code", sample.get("error_code"))
    output["policy_expected_result"] = (
        metric(
            int(
                observations.get("actual_status") == expected
                and observations.get("error_code") == expected_error
            ),
            version=version,
        )
        if expected is not None
        else not_applicable("policy_expectation_missing", version=version)
    )
    return output


def score_sample(sample: dict, artifact: dict, config: dict | None = None) -> dict:
    """Score one predetermined final artifact, with no side effects or network calls."""
    kind = validate_pair(sample, artifact)
    artifact = normalize_artifact(artifact)
    config = metric_config(config, [kind])
    output = {
        "service_failure": metric(
            int(artifact.get("status") in ("failed", "cancelled", "timeout")),
            version=config["metric_version"],
        )
    }
    valid = None
    validity = None
    if kind in CONTEXT_CASES:
        output.update(coverage_metrics(sample, artifact, config))
    if kind == "quiz":
        from .quiz_rubric import score_quiz

        quiz_scores, valid = score_quiz(sample, artifact, config)
        output.update(quiz_scores)
    if kind == "qa":
        from .qa import qa_metrics

        output.update(qa_metrics(sample, artifact, config))
    if kind == "policy":
        output.update(policy_metrics(sample, artifact, config))
    if kind == "practice_generation":
        from .practice import score_practice_generation

        output.update(score_practice_generation(sample, artifact, config))
        validity = output["valid_question_yield"]
        valid = validity.get("details", {}).get("confirmed_valid", 0)
    if kind == "answer_grading":
        from .practice import score_answer_grading

        output.update(score_answer_grading(sample, artifact, config))
    output.update(cost_metrics(artifact, config, valid, validity=validity))
    for name in output:
        if not metric_applies(name, kind):
            raise ValueError(f"metric {name!r} does not apply to {kind!r}")
    return output
