"""JSON-only contracts and metric values shared across isolated processes."""

from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal, DecimalException
from typing import Any

from .metric_registry import CASE_TYPES, RANKING_CUTOFFS, RETRIEVAL_CUTOFFS

METRIC_VERSION = "evidence-v1"
LEARNING_METRIC_VERSION = "learning-mvp-eval.v1"
LEARNING_CASE_TYPES = frozenset({"practice_generation", "answer_grading"})
ADAPTER_OBSERVATIONS = frozenset(
    {
        "practice_validation",
        "grading_context",
        "semantic_reviews",
        "source_validation",
        "grader_calibrated",
        "calibration_profile_hash",
    }
)
_DECIMAL = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


def metric_config(config: dict | None, case_types) -> dict:
    """Resolve one version for a whole run without changing a saved configuration."""
    if config is not None and not isinstance(config, dict):
        raise ValueError("metric config must be a JSON object")  # noqa: TRY004
    kinds = set(case_types)
    if not kinds <= CASE_TYPES:
        raise ValueError("unknown evaluation case_type")
    learning = bool(kinds & LEARNING_CASE_TYPES)
    result = {
        "metric_version": LEARNING_METRIC_VERSION if learning else METRIC_VERSION,
        **(config or {}),
    }
    if learning and result["metric_version"] != LEARNING_METRIC_VERSION:
        raise ValueError(f"new cases require metric_version {LEARNING_METRIC_VERSION}")
    if not isinstance(result["metric_version"], str) or not result["metric_version"]:
        raise ValueError("metric_version must be a nonempty string")
    for field, allowed in (
        ("retrieval_ks", RETRIEVAL_CUTOFFS),
        ("ranking_ks", RANKING_CUTOFFS),
    ):
        if field in result:
            values = result[field]
            if (
                not isinstance(values, list)
                or not values
                or any(
                    type(value) is not int or value not in allowed for value in values
                )
                or len(values) != len(set(values))
            ):
                raise ValueError(
                    f"{field} must use distinct registered cutoffs {allowed}"
                )
    if result["metric_version"] == LEARNING_METRIC_VERSION:
        threshold = result.setdefault("grading_accept_threshold", "1")
        if not isinstance(threshold, str) or not _DECIMAL.fullmatch(threshold):
            raise ValueError(
                "grading_accept_threshold must be a finite Decimal score string"
            )
        try:
            amount = Decimal(threshold)
            valid = amount.is_finite() and 0 <= amount <= 1
        except DecimalException:
            valid = False
        if not valid:
            raise ValueError(
                "grading_accept_threshold must be a finite Decimal score string"
            )
    try:
        json.dumps(result, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("metric config must contain finite JSON values") from exc
    return result


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_text(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    )


def metric(
    numerator: float | None,
    denominator: float = 1,
    *,
    version: str = METRIC_VERSION,
    status: str = "ok",
    reason: str | None = None,
    unit: str = "ratio",
    unknown: int = 0,
    details: dict | None = None,
) -> dict:
    if status not in {"ok", "na", "error"}:
        raise ValueError("metric status must be ok, na, or error")
    if denominator < 0 or not math.isfinite(denominator):
        raise ValueError("invalid metric denominator")
    if numerator is not None and not math.isfinite(numerator):
        raise ValueError("invalid metric numerator")
    if denominator == 0 and status == "ok":
        status, reason = "na", reason or "empty_denominator"
    value = (
        numerator / denominator
        if status == "ok" and numerator is not None and denominator
        else None
    )
    return {
        "status": status,
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "unit": unit,
        "metric_version": version,
        "reason": reason,
        "unknown_count": unknown,
        "applicable_count": int(status != "na"),
        "error_count": int(status == "error"),
        "applicable_samples": int(status != "na"),
        "failure_count": int(status == "error"),
        "details": details or {},
    }


def not_applicable(reason: str, *, version: str = METRIC_VERSION, **details) -> dict:
    return metric(None, 0, status="na", reason=reason, version=version, details=details)


def uncertain(
    numerator: float,
    denominator: float,
    unknown: int,
    reason: str,
    *,
    version: str = METRIC_VERSION,
    **details,
) -> dict:
    lower = numerator / denominator if denominator else None
    upper = min(denominator, numerator + unknown) / denominator if denominator else None
    return metric(
        numerator,
        denominator,
        status="error",
        reason=reason,
        unknown=unknown,
        version=version,
        details={
            "lower_bound": lower,
            "upper_bound": upper,
            "scored_denominator": max(0, denominator - unknown),
            "scoring_coverage": max(0, denominator - unknown) / denominator
            if denominator
            else None,
            "conditional_value": numerator / (denominator - unknown)
            if denominator > unknown
            else None,
            **details,
        },
    )


def validate_pair(sample: dict, artifact: dict) -> str:
    if not isinstance(sample, dict) or not isinstance(artifact, dict):
        raise ValueError("sample and artifact must be JSON objects")  # noqa: TRY004 -- one JSON validation boundary
    kind = sample.get("case_type")
    if kind not in CASE_TYPES or artifact.get("case_type") != kind:
        raise ValueError(
            "sample and artifact case_type must match a supported discriminator"
        )
    if sample.get("sample_id") and artifact.get("sample_id") not in {
        None,
        sample["sample_id"],
    }:
        raise ValueError("sample_id mismatch")
    if kind != "quiz" and artifact.get("questions"):
        raise ValueError("only quiz artifacts may contain generated questions")
    json.dumps(sample, allow_nan=False)
    json.dumps(artifact, allow_nan=False)
    return kind
