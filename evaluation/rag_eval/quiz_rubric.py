"""Question rules, exact adjudicated references, and independent semantic review.

Generated claims, self-reported confidence, and generated objective IDs are never
accepted as evidence that the generated answer is correct.
"""

from __future__ import annotations

import unicodedata

from .contracts import canonical_hash, metric, not_applicable, uncertain
from .evidence import citation_check, context_of, is_covered, provided_ranges

REQUIRED_SEMANTICS = (
    "answer_correctness",
    "source_support",
    "solvability",
    "explanation_correctness",
    "scope_compliance",
    "citation_support",
    "citation_completeness",
)
SEMANTIC_METRICS = (*REQUIRED_SEMANTICS, "stem_premise_support", "distractor_quality")


def normalized(text) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(text)).casefold().split())


def question_schema_valid(question: dict) -> bool:
    if not isinstance(question, dict):
        return False
    if not all(
        isinstance(question.get(key), str) and question[key].strip()
        for key in ("question_id", "stem", "explanation")
    ):
        return False
    refs = question.get("citation_refs", [])
    if (
        not isinstance(refs, list)
        or not all(isinstance(ref, str) and ref for ref in refs)
        or len(refs) != len(set(refs))
    ):
        return False
    kind = question.get("type")
    if kind == "true_false":
        return type(question.get("answer")) is bool and question.get("options", []) in (
            [],
            None,
        )
    if kind not in {"single_choice", "multiple_choice"}:
        return False
    options, answer = question.get("options"), question.get("answer")
    if (
        not isinstance(options, list)
        or not 2 <= len(options) <= 8
        or not isinstance(answer, list)
    ):
        return False
    if not all(
        isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item["id"]
        and isinstance(item.get("text"), str)
        and item["text"].strip()
        for item in options
    ):
        return False
    ids, texts = (
        [item["id"] for item in options],
        [normalized(item["text"]) for item in options],
    )
    if len(set(ids)) != len(ids) or len(set(texts)) != len(texts):
        return False
    if not all(isinstance(item, str) and item in ids for item in answer) or len(
        set(answer)
    ) != len(answer):
        return False
    return (
        len(answer) == 1
        if kind == "single_choice"
        else 1 <= len(answer) <= len(options)
    )


def matching_rubric(sample: dict, question: dict) -> dict | None:
    return next(
        (
            rubric
            for rubric in sample.get("question_rubrics", [])
            if normalized(rubric.get("stem", ""))
            == normalized(question.get("stem", ""))
            and rubric.get("type") == question.get("type")
        ),
        None,
    )


def reference_semantics(
    sample: dict, question: dict, artifact: dict
) -> tuple[dict, str | None, str | None]:
    result = dict.fromkeys(SEMANTIC_METRICS)
    rubric = matching_rubric(sample, question)
    if rubric is None:
        return result, "semantic_review_pending", None
    ranges = provided_ranges(context_of(artifact), sample)
    spans = rubric.get("supporting_spans", [])
    support = bool(spans) and all(is_covered(span, ranges) for span in spans)
    result["source_support"] = support
    result["scope_compliance"] = support
    result["stem_premise_support"] = support
    cited_ids = question.get("citation_refs", [])
    cited_ranges = provided_ranges(
        [item for item in context_of(artifact) if item.get("evidence_id") in cited_ids],
        sample,
    )
    cited_support = bool(spans) and all(
        is_covered(span, cited_ranges) for span in spans
    )
    result["citation_support"] = cited_support
    result["citation_completeness"] = cited_support
    explanation = normalized(question.get("explanation", ""))
    accepted = [
        normalized(rubric.get("reference_explanation", "")),
        *[normalized(text) for text in rubric.get("acceptable_explanations", [])],
    ]
    result["explanation_correctness"] = (
        True if explanation and explanation in accepted else None
    )
    kind = question.get("type")
    if kind == "true_false":
        expected = rubric.get("correct_answer")
        if type(expected) is not bool:
            return result, "reference_answer_missing", rubric.get("objective_id")
        if expected is False:
            refutation_spans = rubric.get("refutation_spans", [])
            if not rubric.get("refutation") or not refutation_spans:
                result["source_support"] = None
                result["solvability"] = None
                return result, "false_refutation_missing", rubric.get("objective_id")
            refutation_covered = all(
                is_covered(span, ranges) for span in refutation_spans
            )
            result["source_support"] = bool(support and refutation_covered)
            if explanation == normalized(question.get("stem", "")):
                result["explanation_correctness"] = False
        result["answer_correctness"] = question.get("answer") is expected
        result["solvability"] = bool(support)
        result["distractor_quality"] = (
            True  # no distractors are applicable to this type
        )
    else:
        expected_texts = rubric.get("correct_answer_texts")
        options = question.get("options", [])
        by_id = {item.get("id"): normalized(item.get("text", "")) for item in options}
        actual = question.get("answer", [])
        if not isinstance(actual, list):
            actual = []
        if not expected_texts:
            return result, "reference_answer_missing", rubric.get("objective_id")
        expected = {normalized(text) for text in expected_texts}
        selected = {by_id[option] for option in actual if option in by_id}
        result["answer_correctness"] = selected == expected
        available = list(by_id.values())
        result["solvability"] = all(available.count(text) == 1 for text in expected)
        if question.get("type") == "single_choice" and len(expected) != 1:
            result["solvability"] = False
        # Plausibility is a separate semantic judgment. A distractor absent from
        # the source cannot thereby be declared false, or plausible.
        if type(rubric.get("distractor_quality")) is bool:
            result["distractor_quality"] = rubric["distractor_quality"]
    reason = (
        "reference_paraphrase_needs_review"
        if result["explanation_correctness"] is None
        else None
    )
    return result, reason, rubric.get("objective_id")


def reviewed_semantics(
    question: dict, artifact: dict, config: dict
) -> tuple[dict | None, str | None]:
    review = next(
        (
            item
            for item in config.get("semantic_reviews", [])
            if item.get("question_id") == question.get("question_id")
        ),
        None,
    )
    if review is None:
        return None, None
    if review.get("status") == "error":
        return dict.fromkeys(SEMANTIC_METRICS), review.get("reason", "judge_error")
    bound = (
        review.get("question_hash")
        in {canonical_hash(question), question.get("_source_question_hash")}
        and review.get("question_hash") is not None
        or review.get("artifact_hash")
        in {canonical_hash(artifact), artifact.get("_source_artifact_hash")}
        and review.get("artifact_hash") is not None
    )
    if not bound:
        return dict.fromkeys(SEMANTIC_METRICS), "review_output_hash_mismatch"
    provenance = review.get("provenance")
    if provenance == "human":
        trusted = bool(review.get("reviewer_id")) and review.get("status") == "ok"
    elif provenance == "judge":
        trusted = (
            review.get("calibrated") is True
            and review.get("status") == "ok"
            and review.get("judge_config_hash") == config.get("judge_config_hash")
            and bool(review.get("judge_config_hash"))
        )
    else:
        trusted = False
    if not trusted:
        return dict.fromkeys(SEMANTIC_METRICS), "independent_review_unverified"
    decisions = review.get("decisions", {})
    return {
        key: decisions.get(key) if type(decisions.get(key)) is bool else None
        for key in SEMANTIC_METRICS
    }, None


def aggregate_decisions(
    values: list[bool | None],
    version: str,
    reason: str = "semantic_review_pending",
    **details,
) -> dict:
    if not values:
        return not_applicable("no_generated_questions", version=version)
    numerator = sum(value is True for value in values)
    unknown = sum(value is None for value in values)
    if unknown:
        return uncertain(
            numerator, len(values), unknown, reason, version=version, **details
        )
    return metric(numerator, len(values), version=version, details=details)


def score_quiz(sample: dict, artifact: dict, config: dict) -> tuple[dict, int]:
    version = config["metric_version"]
    questions = artifact.get("questions", []) or []
    if not isinstance(questions, list):
        raise ValueError("quiz questions must be an array")  # noqa: TRY004 -- one JSON validation boundary
    requested = sample.get("question_count", 0)
    if type(requested) is not int or not 1 <= requested <= 100:
        raise ValueError("question_count must be a positive bounded integer")
    expected = sample.get("expected_outcome", "generate")
    refused = artifact.get("status") == "refused" and not questions
    generated = bool(questions)
    legal_delivery = (
        artifact.get("status", "completed") == "completed"
        and len(questions) == requested
        and artifact.get("delivery_status")
        not in {"invalid", "withheld", "not_delivered"}
    )
    needs_citations = sample.get("source_policy", "strict_docs") != "topic" or bool(
        context_of(artifact)
    )
    output = {
        "question_count_pass": not_applicable("expected_refusal", version=version)
        if expected == "refuse"
        else metric(int(legal_delivery), version=version),
        "requested_question_count": metric(requested, unit="count", version=version),
        "generated_question_count": metric(
            len(questions), unit="count", version=version
        ),
    }
    if expected == "refuse":
        output["correct_refusal"] = metric(int(refused), version=version)
        output["unsupported_generation_rate"] = metric(int(generated), version=version)
        output["answerable_refusal_rate"] = not_applicable(
            "expected_refusal", version=version
        )
    else:
        output["correct_refusal"] = not_applicable(
            "expected_generation", version=version
        )
        output["unsupported_generation_rate"] = not_applicable(
            "expected_generation", version=version
        )
        output["answerable_refusal_rate"] = metric(int(refused), version=version)
    by_id = {
        item["evidence_id"]: item
        for item in context_of(artifact)
        if "evidence_id" in item
    }
    citation_values = {
        key: []
        for key in (
            "citation_id_validity",
            "citation_authorization",
            "citation_hash_match",
            "citation_locator_match",
        )
    }
    semantic_values = {key: [] for key in SEMANTIC_METRICS}
    seen_questions, question_ids, assessments = set(), set(), []
    schema_values, valid_values = [], []
    duplicate_count = 0
    covered_objectives = set()
    reasons = []
    for question in questions:
        if not isinstance(question, dict):
            question = {}
        schema = (
            question_schema_valid(question)
            and question.get("question_id") not in question_ids
        )
        question_ids.add(question.get("question_id"))
        schema_values.append(schema)
        fingerprint = (question.get("type"), normalized(question.get("stem", "")))
        duplicate = fingerprint in seen_questions
        seen_questions.add(fingerprint)
        duplicate_count += int(duplicate)
        refs = (
            question.get("citation_refs", [])
            if isinstance(question.get("citation_refs", []), list)
            else []
        )
        individual_citations = []
        if needs_citations:
            for eid in refs or [None]:
                exists = isinstance(eid, str) and eid in by_id
                citation_values["citation_id_validity"].append(exists)
                checks = (
                    citation_check(by_id[eid], sample, artifact)
                    if exists
                    else {
                        "authorized": False,
                        "hash_match": False,
                        "locator_match": False,
                    }
                )
                for metric_name, check in (
                    ("citation_authorization", "authorized"),
                    ("citation_hash_match", "hash_match"),
                    ("citation_locator_match", "locator_match"),
                ):
                    citation_values[metric_name].append(checks[check])
                individual_citations.extend([exists, *checks.values()])
        semantics, reason, objective = (
            reference_semantics(sample, question, artifact)
            if schema
            else ({key: False for key in SEMANTIC_METRICS}, None, None)
        )
        review, review_reason = reviewed_semantics(question, artifact, config)
        if review is not None:
            semantics, reason = review, review_reason
        if reason:
            reasons.append(reason)
        for name in SEMANTIC_METRICS:
            semantic_values[name].append(semantics[name])
        requirements = [
            schema,
            not duplicate,
            *individual_citations,
            *[
                semantics[name]
                for name in config.get("required_semantics", REQUIRED_SEMANTICS)
            ],
        ]
        valid = (
            False if False in requirements else None if None in requirements else True
        )
        valid_values.append(valid)
        if valid and objective:
            covered_objectives.add(objective)
        assessments.append(
            {
                "question_id": question.get("question_id"),
                "schema_valid": schema,
                "duplicate": duplicate,
                "valid": valid,
                "semantics": semantics,
                "reason": reason,
                "reference_objective_id": objective,
                "evidence_basis": "independent_review"
                if review is not None
                else "exact_reference"
                if matching_rubric(sample, question)
                else "unreviewed",
            }
        )
    output["question_schema_pass"] = aggregate_decisions(schema_values, version)
    output["duplicate_question_rate"] = metric(
        duplicate_count, len(questions), version=version
    )
    for name, values in citation_values.items():
        output[name] = (
            aggregate_decisions(
                values, version, "canonical_source_verification_unavailable"
            )
            if needs_citations
            else not_applicable("model_only_topic_mode", version=version)
        )
    reason = (
        "judge_timeout"
        if "judge_timeout" in reasons
        else next(iter(reasons), "semantic_review_pending")
    )
    for name, values in semantic_values.items():
        output[name] = aggregate_decisions(
            values,
            version,
            reason,
            provenance="deterministic_reference_or_independent_review",
        )
    valid_internal = sum(value is True for value in valid_values)
    unknown_internal = sum(value is None for value in valid_values)
    output["internal_candidate_validity"] = aggregate_decisions(
        valid_values, version, reason
    )
    confirmed = valid_internal if legal_delivery else 0
    possible_unknown = unknown_internal if legal_delivery else 0
    details = {
        "requested_questions": requested,
        "legally_delivered": legal_delivery,
        "confirmed_valid": confirmed,
        "unknown_questions": possible_unknown,
        "question_results": assessments,
        "aggregation": "sum_request_mean_valid_over_sum_requested",
    }
    if expected == "refuse":
        output["valid_question_yield"] = not_applicable(
            "expected_refusal", version=version
        )
        output["full_set_pass"] = not_applicable("expected_refusal", version=version)
        confirmed = 0
    elif not sample.get(
        "source_sufficient", sample.get("answerable_for_requested_count", False)
    ):
        output["valid_question_yield"] = uncertain(
            0,
            requested,
            requested,
            "gold_sufficiency_unreviewed",
            version=version,
            **details,
        )
        output["full_set_pass"] = uncertain(
            0, 1, 1, "gold_sufficiency_unreviewed", version=version
        )
        confirmed = 0
    else:
        output["valid_question_yield"] = (
            uncertain(
                confirmed,
                requested,
                possible_unknown,
                reason,
                version=version,
                **details,
            )
            if possible_unknown
            else metric(confirmed, requested, version=version, details=details)
        )
        if not legal_delivery or any(value is False for value in valid_values):
            output["full_set_pass"] = metric(0, version=version)
        elif possible_unknown:
            output["full_set_pass"] = uncertain(0, 1, 1, reason, version=version)
        else:
            output["full_set_pass"] = metric(
                int(confirmed == requested), version=version
            )
    objectives = sample.get("expected_objectives", [])
    objective_ids = {
        item.get("objective_id") if isinstance(item, dict) else item
        for item in objectives
    }
    output["objective_coverage"] = (
        metric(
            len(covered_objectives & objective_ids),
            len(objective_ids),
            version=version,
            details={
                "covered_objective_ids": sorted(covered_objectives & objective_ids),
                "unknown_question_count": unknown_internal,
            },
        )
        if objective_ids
        else not_applicable("no_objective_gold", version=version)
    )
    return output, confirmed


def prepare_judge_inputs(sample: dict, artifact: dict) -> list[dict]:
    """Prepare only selected answers and explanations, with an explicit rewrite map.

    The unmodified artifact remains the audit record. This does not certify factual
    premises, answer uniqueness, or correctness; the rubric checks those separately.
    """
    evidence = {
        item["evidence_id"]: item
        for item in context_of(artifact)
        if "evidence_id" in item
    }
    inputs = []
    for question in artifact.get("questions", []):
        if not question_schema_valid(question):
            continue
        response, mapping = [], []
        kind = question["type"]
        if kind in {"single_choice", "multiple_choice"}:
            for option in question["options"]:
                selected = option["id"] in question["answer"]
                mapping.append(
                    {
                        "field": f"options.{option['id']}",
                        "included": selected,
                        "role": "selected_answer" if selected else "distractor",
                    }
                )
                if selected:
                    response.append(f"Selected answer: {option['text']}")
        elif question["answer"] is True:
            response.append(question["stem"])
            mapping.append({"field": "true_proposition", "included": True})
        else:
            mapping.append(
                {
                    "field": "false_proposition",
                    "included": False,
                    "reason": "false_stem_requires_refutation_not_literal_support",
                }
            )
        response.append(question["explanation"])
        mapping.append({"field": "explanation", "included": True})
        cited = [
            evidence[eid]
            for eid in question.get("citation_refs", [])
            if eid in evidence
        ]
        inputs.append(
            {
                "question_id": question["question_id"],
                "user_input": question["stem"],
                "response": "\n".join(response),
                "retrieved_contexts": [item["excerpt"] for item in cited],
                "rewrite_mapping": mapping,
                "question_hash": canonical_hash(question),
                "metric_interpretation": "support_of_selected_answer_and_explanation_in_cited_context_only",
            }
        )
    return inputs
