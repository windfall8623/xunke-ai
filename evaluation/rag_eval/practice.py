"""Pure JSON scoring for the two learning-MVP evaluation envelopes.

Private questions and assessments retain the application's field names. Full
private-contract validation belongs to the backend adapter, not a second schema
here. The reserved ``practice_validation`` and ``grading_context`` configuration
observations must be constructed by that adapter from the exact scored snapshot;
dataset, run and user configuration must never supply those observations.

Independent generation quality uses the existing ``semantic_reviews`` protocol.
Neither pipeline validation nor a matching model score proves calibration or
confirmed learning evidence. These functions perform no I/O or accounting.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from decimal import Decimal, DecimalException, localcontext

from .contracts import canonical_hash, metric, not_applicable, uncertain
from .evidence import citation_check, coverage, source_identity
from .quiz_rubric import REQUIRED_SEMANTICS, aggregate_decisions, reviewed_semantics

METRIC_VERSION = "learning-mvp-eval.v1"
GRADE_STATUSES = frozenset({"graded", "needs_review", "failed", "cancelled"})
FAILURE_STATUSES = frozenset({"failed", "cancelled", "timeout"})
CITATION_CHECKS = {
    "citation_id_validity": "identity",
    "citation_authorization": "authorized",
    "citation_hash_match": "hash_match",
    "citation_locator_match": "locator_match",
}
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")


def _version(config: dict) -> str:
    if not isinstance(config, dict):
        raise ValueError("metric config must be a JSON object")  # noqa: TRY004
    version = config.get("metric_version", METRIC_VERSION)
    if version != METRIC_VERSION:
        raise ValueError(f"practice metric_version must be {METRIC_VERSION!r}")
    try:
        json.dumps(config, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("metric config must contain finite JSON values") from exc
    return version


def _pair(sample: dict, artifact: dict, case_type: str) -> None:
    if not isinstance(sample, dict) or not isinstance(artifact, dict):
        raise ValueError("sample and artifact must be JSON objects")  # noqa: TRY004
    if sample.get("case_type") != case_type or artifact.get("case_type") != case_type:
        raise ValueError("sample and artifact case_type must match the scorer")
    identifier = sample.get("sample_id")
    if (
        not isinstance(identifier, str)
        or not identifier
        or artifact.get("sample_id") != identifier
    ):
        raise ValueError("sample_id must be present and match the artifact")
    statuses = {"completed", *FAILURE_STATUSES}
    if case_type == "practice_generation":
        statuses.add("refused")
    if not _in(artifact.get("status"), statuses):
        raise ValueError("artifact execution status is invalid")
    try:
        json.dumps(sample, allow_nan=False)
        json.dumps(artifact, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("sample and artifact must contain finite JSON values") from exc


def _hash(value) -> bool:
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def _in(value, options) -> bool:
    return isinstance(value, str) and value in options


def _all(values) -> bool | None:
    values = list(values)
    if any(value is False for value in values):
        return False
    return None if any(value is None for value in values) else True


def _decisions(
    values, version, reason, *, empty="no_applicable_observations", **details
):
    if not values:
        return not_applicable(empty, version=version, **details)
    return aggregate_decisions(values, version, reason, **details)


def _unknown(reason: str, version: str, **details) -> dict:
    return metric(
        None,
        1,
        version=version,
        status="error",
        unknown=1,
        reason=reason,
        details={"scored_denominator": 0, **details},
    )


def _score(value) -> tuple[Decimal | None, str | None]:
    if value is None:
        return None, "score_missing"
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        return None, "score_invalid"
    try:
        number = Decimal(value)
        if number.is_finite() and Decimal(0) <= number <= Decimal(1):
            return number, None
    except DecimalException:
        pass
    return None, "score_invalid"


def _graded_score(record, *, reference=False):
    if not isinstance(record, dict) or record.get("status") != "graded":
        return None, "reference_grade_unresolved" if reference else "grade_unresolved"
    if reference and (
        not isinstance(record.get("provenance"), str)
        or not record["provenance"].strip()
    ):
        return None, "reference_provenance_missing"
    score, reason = _score(record.get("score"))
    return score, f"reference_{reason}" if reference and reason else reason


def _grade_identity(sample, grade):
    if not isinstance(grade, dict):
        return None, ["grade_artifact_missing"]
    values, errors = [], []
    for field in ("question_version", "rubric_hash", "response_hash"):
        expected, actual = sample.get(field), grade.get(field)
        value = (
            None
            if expected is None or actual is None
            else _hash(expected) and _hash(actual) and expected == actual
        )
        values.append(value)
        if value is not True:
            errors.append(field)
    assessment = grade.get("assessment")
    if isinstance(assessment, dict):
        for field in ("rubric_version", "rubric_hash", "grader_version"):
            if field not in assessment and (
                field != "rubric_hash" and field not in grade
            ):
                continue
            # The frozen minimal grading boundary does not repeat rubric_hash in
            # its assessment; a declared nested identity is always checked.
            if field == "rubric_hash" and field not in assessment:
                continue
            actual, nested = grade.get(field), assessment.get(field)
            value = None if actual is None or nested is None else actual == nested
            values.append(value)
            if value is not True:
                errors.append(f"assessment.{field}")
    question, answer = sample.get("question"), sample.get("answer")
    for field, payload in (("question", question), ("answer", answer)):
        if isinstance(payload, dict):
            values.append(payload.get("type") == sample.get("question_type"))
            if values[-1] is not True:
                errors.append(f"{field}.type")
    return _all(values), errors


def _confirmation(assessment, grade, config):
    if not isinstance(assessment, dict):
        return None
    status = assessment.get("status")
    confirmation = assessment.get("confirmation")
    independent = assessment.get("independent_eligible")
    source = assessment.get("source")
    if status is None or confirmation is None or source is None:
        return None
    if not _in(status, GRADE_STATUSES) or not _in(
        confirmation, {"confirmed", "provisional"}
    ):
        return False
    if not _in(source, {"deterministic", "model", "human"}):
        return False
    if independent is not None and type(independent) is not bool:
        return False
    if status == "graded":
        if _score(assessment.get("score"))[0] is None:
            return False
    elif assessment.get("score") is not None or confirmation != "provisional":
        return False
    if independent is True and (status != "graded" or confirmation != "confirmed"):
        return False
    if source == "deterministic" and (
        status != "graded" or confirmation != "confirmed"
    ):
        return False
    if source == "model" and confirmation == "confirmed":
        profile = config.get("calibration_profile_hash")
        if not (
            config.get("grader_calibrated") is True
            and _hash(profile)
            and grade.get("calibration_profile_hash") == profile
        ):
            return False
    return None if independent is None else True


def _citation_observations(
    groups, sample, context, *, context_known=True, allowed_refs=None
):
    """Check every declared citation occurrence, retaining unverified locators."""
    pack = context.get("evidence_pack", {})
    evidence = pack.get("evidence", []) if isinstance(pack, dict) else []
    provided = pack.get("provided_evidence_ids") if isinstance(pack, dict) else None
    context_known = (
        context_known and isinstance(evidence, list) and isinstance(provided, list)
    )
    items = (
        [item for item in evidence if isinstance(item, dict)]
        if isinstance(evidence, list)
        else []
    )
    counts = Counter(
        item.get("evidence_id")
        for item in items
        if isinstance(item.get("evidence_id"), str)
    )
    by_id = {
        item["evidence_id"]: item
        for item in items
        if isinstance(item.get("evidence_id"), str)
    }
    provided_ids = (
        {item for item in provided if isinstance(item, str)}
        if isinstance(provided, list)
        else set()
    )
    sources = {
        source_identity(ref)
        for ref in sample.get("source_refs", [])
        if isinstance(ref, dict)
    }
    values = {name: [] for name in CITATION_CHECKS}
    group_states, ref_states = [], []
    for refs in groups:
        states = []
        ref_counts = Counter(ref for ref in refs if isinstance(ref, str))
        for ref in refs:
            if (
                not isinstance(ref, str)
                or not ref
                or ref_counts[ref] != 1
                or (allowed_refs is not None and ref not in allowed_refs)
            ):
                checks = dict.fromkeys(CITATION_CHECKS.values(), False)
            elif not context_known:
                checks = dict.fromkeys(CITATION_CHECKS.values())
            elif ref not in by_id or counts[ref] != 1 or ref not in provided_ids:
                checks = dict.fromkeys(CITATION_CHECKS.values(), False)
            else:
                item = by_id[ref]
                checks = {
                    "identity": (
                        item.get("source_type", "document") == "document"
                        and source_identity(item) in sources
                    )
                    if sources
                    else None,
                    **citation_check(item, sample, context),
                }
            for name, check in CITATION_CHECKS.items():
                values[name].append(checks[check])
            state = _all(checks.values())
            states.append(state)
            ref_states.append((ref, state))
        group_states.append(_all(states))
    return values, group_states, ref_states, by_id


def _grading_context(sample, grade, config):
    context = config.get("grading_context")
    if not isinstance(context, dict) or not isinstance(grade, dict):
        return {}, False
    if context.get("sample_id") != sample["sample_id"]:
        return {}, False
    question = sample.get("question")
    if not isinstance(question, dict) or context.get("question_hash") != canonical_hash(
        question
    ):
        return {}, False
    for field in ("question_version", "rubric_hash", "response_hash"):
        expected = sample.get(field)
        if (
            not _hash(expected)
            or context.get(field) != expected
            or grade.get(field) != expected
        ):
            return {}, False
    scope = context.get("scope_fingerprint")
    if not _hash(scope) or scope != grade.get("scope_fingerprint"):
        return {}, False
    if "scope_fingerprint" in sample and scope != sample["scope_fingerprint"]:
        return {}, False
    return context, True


def _grading_citations(sample, grade, assessment, config, version):
    refs = assessment.get("evidence_refs", []) if isinstance(assessment, dict) else []
    refs = refs if isinstance(refs, list) else [None]
    citation_groups = [refs]
    criteria = (
        assessment.get("criterion_results", []) if isinstance(assessment, dict) else []
    )
    if isinstance(criteria, list):
        for criterion in criteria:
            if isinstance(criterion, dict) and "evidence_refs" in criterion:
                cited = criterion["evidence_refs"]
                citation_groups.append(cited if isinstance(cited, list) else [None])
    elif criteria is not None:
        citation_groups.append([None])
    context, known = _grading_context(sample, grade, config)
    question = sample.get("question")
    question_refs = (
        question.get("citation_refs") if isinstance(question, dict) else None
    )
    allowed_refs = (
        {ref for ref in question_refs if isinstance(ref, str)}
        if isinstance(question_refs, list)
        else None
    )
    values, states, ref_states, by_id = _citation_observations(
        citation_groups, sample, context, context_known=known, allowed_refs=allowed_refs
    )
    output = {
        name: _decisions(
            observed,
            version,
            "grading_context_unverified",
            empty="no_assessment_citations",
        )
        for name, observed in values.items()
    }
    output["citation_support"] = _decisions(
        [False if state is False else None for _, state in ref_states],
        version,
        "grading_citation_support_unreviewed",
        empty="no_assessment_citations",
    )
    groups = sample.get("gold_evidence_groups", [])
    if not groups:
        output["citation_completeness"] = not_applicable(
            "no_required_citation_gold", version=version
        )
    elif not known:
        output["citation_completeness"] = uncertain(
            0, len(groups), len(groups), "grading_context_unverified", version=version
        )
    else:
        verified = [by_id[ref] for ref, state in ref_states if state is True]
        unresolved = [
            by_id[ref] for ref, state in ref_states if state is None and ref in by_id
        ]
        hit, unknown = coverage(groups, verified, sample)
        possible, remaining = coverage(groups, verified + unresolved, sample)
        unknown_groups = (set(unknown) | set(possible) | set(remaining)) - set(hit)
        details = {"hit_group_ids": hit, "unknown_group_ids": sorted(unknown_groups)}
        output["citation_completeness"] = (
            uncertain(
                len(hit),
                len(groups),
                len(unknown_groups),
                "source_validation_unreported",
                version=version,
                **details,
            )
            if unknown_groups
            else metric(len(hit), len(groups), version=version, details=details)
        )
    return output, _all(states)


def score_answer_grading(sample: dict, artifact: dict, config: dict) -> dict[str, dict]:
    """Compare immutable grade identities, explicit states and finite Decimal scores."""
    version = _version(config)
    _pair(sample, artifact, "answer_grading")
    threshold, reason = _score(config.get("grading_accept_threshold", "1"))
    if reason:
        raise ValueError(
            "grading_accept_threshold must be a finite Decimal score string"
        )
    grade = artifact.get("grade")
    assessment = grade.get("assessment") if isinstance(grade, dict) else None
    completed = artifact["status"] == "completed"
    technical_failure = artifact["status"] in FAILURE_STATUSES
    actual_status = (
        assessment.get("status")
        if completed and isinstance(assessment, dict)
        else "cancelled"
        if artifact["status"] == "cancelled"
        else "failed"
        if technical_failure
        else None
    )
    expected = sample.get("expected_grade_status")
    expected_error = sample.get("expected_error_code")
    error_match = artifact.get("error_code") == expected_error
    clean_failure = technical_failure and grade is None
    outcome_match = (
        actual_status == expected and error_match and (completed or clean_failure)
    )
    output = {
        "grading_status_match": (
            metric(int(outcome_match), version=version)
            if _in(expected, GRADE_STATUSES)
            else _unknown("expected_grade_status_missing", version)
        ),
        "grading_failure_behavior_match": (
            metric(
                int(clean_failure and error_match and actual_status == expected),
                version=version,
                details={
                    "expected_error_code": expected_error,
                    "actual_error_code": artifact.get("error_code"),
                },
            )
            if expected_error is not None
            else not_applicable("no_expected_technical_failure", version=version)
        ),
        "grading_review_rate": _decisions(
            [
                actual_status == "needs_review"
                if _in(actual_status, GRADE_STATUSES)
                else None
            ],
            version,
            "grade_status_unreported",
        ),
        "grading_failure_rate": _decisions(
            [
                _in(actual_status, {"failed", "cancelled"})
                if _in(actual_status, GRADE_STATUSES)
                else None
            ],
            version,
            "grade_status_unreported",
        ),
    }
    identity, identity_errors = _grade_identity(sample, grade)
    output["grading_identity_match"] = (
        not_applicable("expected_technical_failure_without_grade", version=version)
        if clean_failure and outcome_match and expected_error is not None
        else _decisions(
            [identity], version, "grading_identity_unverified", fields=identity_errors
        )
    )
    prediction, prediction_reason = _graded_score(assessment)
    reference, reference_reason = _graded_score(
        sample.get("reference_grade"), reference=True
    )
    comparison_reason = (
        "grading_identity_mismatch"
        if identity is False
        else "grading_identity_unverified"
        if identity is None
        else "execution_incomplete"
        if not completed
        else prediction_reason or reference_reason
    )
    if comparison_reason:
        output["grading_abs_error"] = _unknown(comparison_reason, version)
    else:
        absolute_error = None
        try:
            with localcontext() as context:
                context.prec = (
                    max(
                        len(prediction.as_tuple().digits),
                        len(reference.as_tuple().digits),
                        28,
                    )
                    + 2
                )
                absolute_error = abs(prediction - reference)
        except DecimalException:
            pass
        value = float(absolute_error) if absolute_error is not None else None
        details = {
            "absolute_error_decimal": str(absolute_error)
            if absolute_error is not None
            else None,
            "reference_provenance": sample["reference_grade"]["provenance"],
        }
        if prediction != reference and value == 0:
            details["absolute_error_decimal"] = None
            details["prediction_score_decimal"] = str(prediction)
            details["reference_score_decimal"] = str(reference)
        output["grading_abs_error"] = (
            _unknown("score_precision_unrepresentable", version, **details)
            if value is None
            or not math.isfinite(value)
            or (prediction != reference and value == 0)
            else metric(value, version=version, details=details)
        )
    if reference_reason:
        output["grading_false_accept_rate"] = _unknown(
            reference_reason, version, denominator_known=False
        )
    elif reference >= threshold:
        output["grading_false_accept_rate"] = not_applicable(
            "reference_already_accepted",
            version=version,
            denominator_known=True,
            acceptance_threshold=str(threshold),
        )
    elif comparison_reason:
        output["grading_false_accept_rate"] = _unknown(
            comparison_reason,
            version,
            denominator_known=True,
            acceptance_threshold=str(threshold),
        )
    else:
        output["grading_false_accept_rate"] = metric(
            int(prediction >= threshold),
            version=version,
            details={
                "denominator_known": True,
                "denominator_kind": "reference_negative_answers",
                "acceptance_threshold": str(threshold),
            },
        )
    policy = (
        clean_failure if technical_failure else _confirmation(assessment, grade, config)
    )
    output["confirmation_policy_pass"] = _decisions(
        [policy], version, "confirmation_policy_unreported"
    )
    citation_metrics, citations_valid = _grading_citations(
        sample, grade, assessment, config, version
    )
    output.update(citation_metrics)
    if not completed or _in(actual_status, {"needs_review", "failed", "cancelled"}):
        eligible = False
    elif isinstance(assessment, dict):
        independent = assessment.get("independent_eligible")
        eligible = _all(
            [
                actual_status == "graded",
                prediction is not None,
                assessment.get("confirmation") == "confirmed"
                if "confirmation" in assessment
                else None,
                independent if type(independent) is bool else None,
                policy,
                identity,
                citations_valid,
            ]
        )
    else:
        eligible = None
    output["learning_evidence_eligible"] = _decisions(
        [eligible], version, "learning_evidence_state_unverified"
    )
    return output


def _practice_validation(practice, questions, config):
    observation = config.get("practice_validation")
    if not isinstance(observation, dict) or observation.get(
        "artifact_hash"
    ) != canonical_hash(practice):
        return None
    if not all(
        isinstance(question, dict) and isinstance(question.get("id"), str)
        for question in questions
    ):
        return None
    question_ids = [question["id"] for question in questions]
    results = observation.get("question_results")
    if (
        len(set(question_ids)) != len(question_ids)
        or not isinstance(results, list)
        or len(results) != len(questions)
    ):
        return None
    if not all(
        isinstance(result, dict) and isinstance(result.get("question_id"), str)
        for result in results
    ):
        return None
    by_id = {result["question_id"]: result for result in results}
    if len(by_id) != len(results) or set(by_id) != set(question_ids):
        return None
    for field in ("question_versions", "rubric_hashes"):
        mapping = observation.get(field)
        if not isinstance(mapping, dict) or set(mapping) != set(question_ids):
            return None
    for question in questions:
        result = by_id[question["id"]]
        if type(result.get("schema_valid")) is not bool or result.get(
            "question_hash"
        ) != canonical_hash(question):
            return None
        for field in ("question_versions", "rubric_hashes"):
            value = observation[field][question["id"]]
            if not _hash(value) and not (
                result["schema_valid"] is False and value is None
            ):
                return None
    return {**observation, "by_id": by_id}


def _practice_reviews(question, practice, config):
    if not isinstance(question, dict):
        return dict.fromkeys(REQUIRED_SEMANTICS), "semantic_review_pending"
    # Reuse only the independent review protocol, never quiz question validation.
    view = {
        **question,
        "question_id": question.get("id"),
        "_source_question_hash": canonical_hash(question),
    }
    try:
        artifact_view = {**practice, "_source_artifact_hash": canonical_hash(practice)}
        review, reason = reviewed_semantics(view, artifact_view, config)
    except (AttributeError, TypeError, ValueError):
        return dict.fromkeys(REQUIRED_SEMANTICS), "independent_review_unverified"
    if review is None:
        return dict.fromkeys(REQUIRED_SEMANTICS), "semantic_review_pending"
    return {name: review[name] for name in REQUIRED_SEMANTICS}, reason


def score_practice_generation(
    sample: dict, artifact: dict, config: dict
) -> dict[str, dict]:
    """Score private practice delivery using bound validation and independent review."""
    version = _version(config)
    _pair(sample, artifact, "practice_generation")
    spec = sample.get("spec")
    requested = spec.get("question_count") if isinstance(spec, dict) else None
    if type(requested) is not int or not 3 <= requested <= 10:
        raise ValueError("PracticeSpec question_count must be an integer from 3 to 10")
    expected = sample.get("expected_outcome")
    if not _in(expected, {"generate", "refuse", "failed"}):
        raise ValueError("practice expected_outcome must be generate, refuse or failed")
    raw_practice = artifact.get("practice")
    practice = raw_practice if isinstance(raw_practice, dict) else {}
    questions = practice.get("questions", [])
    if not isinstance(questions, list):
        raise ValueError("private practice questions must be an array")  # noqa: TRY004
    empty_output = raw_practice is None
    expected_error = sample.get("expected_error_code")
    error_match = artifact.get("error_code") == expected_error
    refused = artifact["status"] == "refused" and empty_output and error_match
    failed = artifact["status"] in FAILURE_STATUSES and empty_output and error_match
    generated = (
        artifact["status"] == "completed"
        and bool(questions)
        and artifact.get("error_code") is None
    )
    legal_delivery = generated and len(questions) == requested
    outcome = {
        "generate": generated and expected_error is None,
        "refuse": refused,
        "failed": failed,
    }[expected]
    failure_metric = (
        metric(int(failed), version=version)
        if isinstance(expected_error, str) and expected_error.strip()
        else _unknown("expected_error_code_missing", version)
    )
    output = {
        "practice_outcome_match": failure_metric
        if expected == "failed"
        else metric(int(outcome), version=version),
        "practice_failure_behavior_match": failure_metric
        if expected == "failed"
        else not_applicable("no_expected_technical_failure", version=version),
        "requested_question_count": metric(requested, unit="count", version=version),
        "generated_question_count": metric(
            len(questions), unit="count", version=version
        ),
        "question_count_pass": metric(int(legal_delivery), version=version)
        if expected == "generate"
        else not_applicable(f"expected_{expected}", version=version),
        "correct_refusal": metric(int(refused), version=version)
        if expected == "refuse"
        else not_applicable(f"expected_{expected}", version=version),
        "unsupported_generation_rate": metric(int(bool(questions)), version=version)
        if expected == "refuse"
        else not_applicable(f"expected_{expected}", version=version),
        "answerable_refusal_rate": metric(
            int(artifact["status"] == "refused"), version=version
        )
        if expected == "generate"
        else not_applicable(f"expected_{expected}", version=version),
    }
    observation = _practice_validation(practice, questions, config)
    schemas, identities, duplicate_values, semantic_values, valid_values = (
        [],
        [],
        [],
        {name: [] for name in REQUIRED_SEMANTICS},
        [],
    )
    reasons, question_results, seen_versions = [], [], set()
    refs = [
        question.get("citation_refs", []) if isinstance(question, dict) else []
        for question in questions
    ]
    citation_values, citation_states, _, _ = _citation_observations(
        [ref or [None] if isinstance(ref, list) else [None] for ref in refs],
        sample,
        practice,
    )
    for index, question in enumerate(questions):
        identifier = question.get("id") if isinstance(question, dict) else None
        schema, identity, duplicate = None, None, None
        if observation is not None:
            schema = observation["by_id"][identifier]["schema_valid"]
            identity = schema and all(
                isinstance(practice.get(field), dict)
                and set(practice[field]) == set(observation[field])
                and practice[field].get(identifier) == observation[field][identifier]
                for field in ("question_versions", "rubric_hashes")
            )
            question_version = observation["question_versions"][identifier]
            if question_version is not None:
                duplicate = question_version in seen_versions
                seen_versions.add(question_version)
        semantics, reason = _practice_reviews(question, practice, config)
        if reason:
            reasons.append(reason)
        for name in REQUIRED_SEMANTICS:
            semantic_values[name].append(semantics[name])
        schemas.append(schema)
        identities.append(identity)
        duplicate_values.append(duplicate)
        valid = _all(
            [
                schema,
                identity,
                not duplicate if duplicate is not None else None,
                citation_states[index],
                *semantics.values(),
            ]
        )
        valid_values.append(valid)
        question_results.append(
            {
                "question_id": identifier,
                "schema_valid": schema,
                "identity_valid": identity,
                "duplicate": duplicate,
                "valid": valid,
                "reason": reason,
            }
        )
    reason = next(iter(reasons), "semantic_review_pending")
    output["question_schema_pass"] = _decisions(
        schemas,
        version,
        "practice_validation_unverified",
        empty="no_generated_questions",
    )
    output["practice_identity_match"] = _decisions(
        identities,
        version,
        "practice_validation_unverified",
        empty="no_generated_questions",
    )
    output["duplicate_question_rate"] = _decisions(
        duplicate_values,
        version,
        "practice_validation_unverified",
        empty="no_generated_questions",
    )
    for name, values in citation_values.items():
        output[name] = _decisions(
            values,
            version,
            "canonical_source_verification_unavailable",
            empty="no_generated_questions",
        )
    for name, values in semantic_values.items():
        output[name] = _decisions(
            values,
            version,
            reason,
            empty="no_generated_questions",
            provenance="independent_review",
        )
    output["internal_candidate_validity"] = _decisions(
        valid_values, version, reason, empty="no_generated_questions"
    )
    confirmed = sum(value is True for value in valid_values) if legal_delivery else 0
    unknown = sum(value is None for value in valid_values) if legal_delivery else 0
    details = {
        "requested_questions": requested,
        "legally_delivered": legal_delivery,
        "confirmed_valid": confirmed,
        "unknown_questions": unknown,
        "question_results": question_results,
    }
    if expected != "generate":
        output["valid_question_yield"] = not_applicable(
            f"expected_{expected}", version=version
        )
        output["full_set_pass"] = not_applicable(
            f"expected_{expected}", version=version
        )
    else:
        output["valid_question_yield"] = (
            uncertain(confirmed, requested, unknown, reason, version=version, **details)
            if unknown
            else metric(confirmed, requested, version=version, details=details)
        )
        output["full_set_pass"] = (
            metric(0, version=version)
            if not legal_delivery or any(value is False for value in valid_values)
            else uncertain(0, 1, 1, reason, version=version)
            if unknown
            else metric(int(confirmed == requested), version=version)
        )
    return output
