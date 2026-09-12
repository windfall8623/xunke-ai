import copy

import pytest

from rag_eval.metrics import score_sample
from rag_eval.quiz_rubric import prepare_judge_inputs


def test_false_judgment_uses_explicit_refutation(quiz_case, quiz_artifact):
    result = score_sample(quiz_case, quiz_artifact)
    assert result["answer_correctness"]["value"] == 1
    assert result["source_support"]["value"] == 1
    assert result["valid_question_yield"]["value"] == 1
    assert result["full_set_pass"]["value"] == 1


def test_incorrect_distractors_do_not_lower_positive_fact_support(
    quiz_case, quiz_artifact
):
    payloads = prepare_judge_inputs(quiz_case, quiz_artifact)
    first = next(item for item in payloads if item["question_id"] == "q1")
    assert "100 C" in first["response"]
    assert "900 C" not in first["response"] and "40 C" not in first["response"]
    false = next(item for item in payloads if item["question_id"] == "q2")
    assert "0 C" in false["response"] and "50 C" not in false["response"]
    assert any(
        item["field"] == "false_proposition" and item["included"] is False
        for item in false["rewrite_mapping"]
    )


def test_unmentioned_false_statement_is_unknown_without_refutation(
    quiz_case, quiz_artifact
):
    quiz_case["question_rubrics"][1].pop("refutation")
    result = score_sample(quiz_case, quiz_artifact)
    assert result["answer_correctness"]["status"] == "error"
    assert result["answer_correctness"]["unknown_count"] == 1
    assert result["valid_question_yield"]["details"]["lower_bound"] == pytest.approx(
        2 / 3
    )
    assert result["valid_question_yield"]["details"]["upper_bound"] == 1


def test_false_label_with_wrong_explanation_is_invalid(quiz_case, quiz_artifact):
    quiz_artifact["questions"][1]["explanation"] = "Ice melts at 50 C."
    result = score_sample(quiz_case, quiz_artifact)
    assert result["valid_question_yield"]["value"] == pytest.approx(2 / 3)
    assert result["full_set_pass"]["value"] == 0


def test_option_reordering_compares_answer_text_semantics(quiz_case, quiz_artifact):
    question = quiz_artifact["questions"][0]
    question["options"][0]["id"] = "C"
    question["options"][2]["id"] = "A"
    question["answer"] = ["C"]
    assert score_sample(quiz_case, quiz_artifact)["answer_correctness"]["value"] == 1


def test_multiple_choice_requires_the_whole_correct_set(quiz_case, quiz_artifact):
    question = quiz_artifact["questions"][0]
    question["type"] = "multiple_choice"
    quiz_case["question_rubrics"][0]["type"] = "multiple_choice"
    quiz_case["question_rubrics"][0]["correct_answer_texts"] = ["100 C", "40 C"]
    question["answer"] = ["A"]
    assert score_sample(quiz_case, quiz_artifact)["answer_correctness"][
        "value"
    ] == pytest.approx(2 / 3)


def test_boolean_string_is_schema_error(quiz_case, quiz_artifact):
    quiz_artifact["questions"][1]["answer"] = "false"
    result = score_sample(quiz_case, quiz_artifact)
    assert result["question_schema_pass"]["value"] == pytest.approx(2 / 3)
    assert result["valid_question_yield"]["value"] == pytest.approx(2 / 3)


def test_correct_refusal_is_excluded_from_generation_yield(quiz_case, quiz_artifact):
    quiz_case["expected_outcome"] = "refuse"
    quiz_artifact["status"] = "refused"
    quiz_artifact["questions"] = []
    result = score_sample(quiz_case, quiz_artifact)
    assert result["correct_refusal"]["value"] == 1
    assert result["unsupported_generation_rate"]["value"] == 0
    assert result["valid_question_yield"]["status"] == "na"
    assert result["valid_question_yield"]["denominator"] == 0
    assert result["question_count_pass"]["status"] == "na"


def test_failed_generate_request_counts_zero_yield(quiz_case, quiz_artifact):
    quiz_artifact["status"] = "failed"
    quiz_artifact["questions"] = []
    result = score_sample(quiz_case, quiz_artifact)
    assert result["valid_question_yield"]["value"] == 0
    assert result["valid_question_yield"]["denominator"] == 3
    assert result["service_failure"]["value"] == 1
    assert result["cost_per_valid_question_cny"]["status"] == "na"


def test_underproduction_is_not_a_legal_full_delivery(quiz_case, quiz_artifact):
    quiz_artifact["questions"] = quiz_artifact["questions"][:2]
    result = score_sample(quiz_case, quiz_artifact)
    assert result["valid_question_yield"]["value"] == 0
    assert result["full_set_pass"]["value"] == 0
    assert result["question_count_pass"]["value"] == 0
    assert result["internal_candidate_validity"]["value"] == 1


def test_duplicate_questions_do_not_increase_yield(quiz_case, quiz_artifact):
    quiz_artifact["questions"][2] = copy.deepcopy(quiz_artifact["questions"][0])
    quiz_artifact["questions"][2]["question_id"] = "q3"
    result = score_sample(quiz_case, quiz_artifact)
    assert result["valid_question_yield"]["value"] == pytest.approx(2 / 3)
    assert result["duplicate_question_rate"]["value"] == pytest.approx(1 / 3)


def test_unknown_semantics_do_not_become_confirmed_valid_output(
    quiz_case, quiz_artifact
):
    quiz_case.pop("question_rubrics")
    for question in quiz_artifact["questions"]:
        question["claims"] = [{"supported": True}]
    result = score_sample(quiz_case, quiz_artifact)
    assert result["valid_question_yield"]["status"] == "error"
    assert result["valid_question_yield"]["value"] is None
    assert result["valid_question_yield"]["details"]["lower_bound"] == 0
    assert result["valid_question_yield"]["details"]["upper_bound"] == 1
    assert (
        result["cost_per_valid_question_cny"]["reason"] == "no_confirmed_valid_output"
    )


def test_judge_timeout_is_not_generator_failure(quiz_case, quiz_artifact):
    quiz_case.pop("question_rubrics")
    config = {
        "semantic_reviews": [
            {
                "question_id": q["question_id"],
                "status": "error",
                "reason": "judge_timeout",
            }
            for q in quiz_artifact["questions"]
        ]
    }
    result = score_sample(quiz_case, quiz_artifact, config)
    assert result["answer_correctness"]["reason"] == "judge_timeout"
    assert result["service_failure"]["value"] == 0


def test_forged_or_unprovided_citation_fails(quiz_case, quiz_artifact):
    quiz_artifact["questions"][0]["citation_refs"] = ["not-in-prompt"]
    result = score_sample(quiz_case, quiz_artifact)
    assert result["citation_id_validity"]["value"] == pytest.approx(2 / 3)
    assert result["valid_question_yield"]["value"] == pytest.approx(2 / 3)


def test_source_position_without_authoritative_text_is_unknown(
    quiz_case, quiz_artifact
):
    quiz_case["source_refs"][0].pop("canonical_text")
    result = score_sample(quiz_case, quiz_artifact)
    assert result["citation_hash_match"]["value"] == 1
    assert result["citation_locator_match"]["status"] == "error"


def test_changed_citation_quote_fails_integrity(quiz_case, quiz_artifact):
    quiz_artifact["evidence"][0]["excerpt"] += " Fabricated."
    result = score_sample(quiz_case, quiz_artifact)
    assert result["citation_hash_match"]["value"] == 0
    assert result["citation_locator_match"]["value"] == 0
    assert result["valid_question_yield"]["value"] == 0


def test_citing_irrelevant_evidence_cannot_use_uncited_context_for_support(
    quiz_case, quiz_artifact
):
    from conftest import make_evidence

    source = quiz_case["source_refs"][0]
    quiz_artifact["evidence"].append(make_evidence(source, 42, 59, "irrelevant"))
    quiz_artifact["context_evidence_ids"].append("irrelevant")
    quiz_artifact["questions"][0]["citation_refs"] = ["irrelevant"]
    result = score_sample(quiz_case, quiz_artifact)
    assert result["citation_support"]["value"] == pytest.approx(2 / 3)
    assert result["valid_question_yield"]["value"] == pytest.approx(2 / 3)


def test_native_backend_question_and_evidence_shape_is_normalized(
    quiz_case, quiz_artifact
):
    native = copy.deepcopy(quiz_artifact)
    native["schema_version"] = "quiz-artifact.v1"
    native["evidence_pack"] = {
        "evidence": native.pop("evidence"),
        "provided_evidence_ids": native.pop("context_evidence_ids"),
        "context_tokens": 30,
    }
    for evidence in native["evidence_pack"]["evidence"]:
        evidence["document_version_id"] = evidence.pop("source_version_id")
    for question in native["questions"]:
        question["id"] = question.pop("question_id")
        if question["type"] == "true_false":
            question["type"] = "judge"
            question["options"] = [
                {"key": "Y", "text": "正确"},
                {"key": "N", "text": "错误"},
            ]
            question["answer"] = ["Y"] if question["answer"] else ["N"]
        else:
            question["type"] = "single"
            question["options"] = [
                {"key": item["id"], "text": item["text"]}
                for item in question["options"]
            ]
    assert score_sample(quiz_case, native)["valid_question_yield"]["value"] == 1
