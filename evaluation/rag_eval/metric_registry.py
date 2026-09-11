"""Explicit metric applicability for the six evaluation case types.

Legacy producers still accept arbitrary stage names and ranking cutoffs. This
table intentionally recognizes only the inventoried names and finite cutoffs;
formal E01 integration must validate producer configuration against this table.
"""

from __future__ import annotations

from types import MappingProxyType

CASE_TYPES = frozenset(
    {"retrieval", "quiz", "policy", "qa", "practice_generation", "answer_grading"}
)
CONTEXT_CASES = frozenset({"retrieval", "quiz", "qa", "practice_generation"})
GENERATION_CASES = frozenset({"quiz", "practice_generation"})
CITATION_CASES = frozenset({"quiz", "qa", "practice_generation", "answer_grading"})
QA_CASES = frozenset({"qa"})
PRACTICE_CASES = frozenset({"practice_generation"})
GRADING_CASES = frozenset({"answer_grading"})
POLICY_CASES = frozenset({"policy"})

# Existing ranking tests use 1 and 2; persisted V1 runs use 5, 10 and 20.
RANKING_CUTOFFS = (1, 2, 5, 10, 20)
RETRIEVAL_CUTOFFS = (5, 10, 20)

METRIC_CASE_TYPES = MappingProxyType(
    {
        "service_failure": CASE_TYPES,
        "provider_call_count": CASE_TYPES,
        "provider_error_rate": CASE_TYPES,
        "retry_count": CASE_TYPES,
        "input_tokens": CASE_TYPES,
        "output_tokens": CASE_TYPES,
        "total_cost_cny": CASE_TYPES,
        "generation_cost_cny": CASE_TYPES,
        "judge_cost_cny": CASE_TYPES,
        "index_cost_cny": CASE_TYPES,
        "retrieval_cost_cny": CASE_TYPES,
        "rerank_cost_cny": CASE_TYPES,
        # cost_metrics maps llm -> generation and reranker -> rerank. The other
        # provider stages are the unchanged Usage/PracticeCallUsage spellings.
        "embedding_cost_cny": CASE_TYPES,
        "search_cost_cny": CASE_TYPES,
        "fetch_cost_cny": CASE_TYPES,
        "images_cost_cny": CASE_TYPES,
        "unknown_cost_cny": CASE_TYPES,
        # These E01 task-ledger metrics require formal runtime integration.
        "reserved_cost_cny": CASE_TYPES,
        "unknown_reserved_cost_cny": CASE_TYPES,
        "unknown_call_count": CASE_TYPES,
        "queue_latency_ms": CASE_TYPES,
        "execution_latency_ms": CASE_TYPES,
        "end_to_end_latency_ms": CASE_TYPES,
        "total_latency_ms": CASE_TYPES,
        # Durable provider-meter timings are diagnostics, independent of whether
        # a given case has a retrieval-quality denominator.
        "provider_llm_latency_ms": CASE_TYPES,
        "provider_embedding_latency_ms": CASE_TYPES,
        "provider_reranker_latency_ms": CASE_TYPES,
        "provider_search_latency_ms": CASE_TYPES,
        "provider_fetch_latency_ms": CASE_TYPES,
        "provider_images_latency_ms": CASE_TYPES,
        "retrieval_latency_ms": CONTEXT_CASES,
        "generation_latency_ms": GENERATION_CASES,
        "generate_latency_ms": frozenset({"qa", "practice_generation"}),
        "rewrite_latency_ms": QA_CASES,
        "semantic_latency_ms": frozenset({"qa", "practice_generation"}),
        "qa_latency_ms": QA_CASES,
        "grading_latency_ms": GRADING_CASES,
        "context_evidence_group_recall": CONTEXT_CASES,
        "context_all_evidence": CONTEXT_CASES,
        "context_redundancy": CONTEXT_CASES,
        "evidence_retention": CONTEXT_CASES,
        "context_tokens": CONTEXT_CASES,
        "context_budget_pass": CONTEXT_CASES,
        "candidate_count": CONTEXT_CASES,
        **{
            f"{name}@{cutoff}": CONTEXT_CASES
            for name in ("evidence_group_recall", "all_evidence")
            for cutoff in RETRIEVAL_CUTOFFS
        },
        **{
            f"{name}@{cutoff}": CONTEXT_CASES
            for name in ("mrr", "ndcg")
            for cutoff in RANKING_CUTOFFS
        },
        "citation_id_validity": CITATION_CASES,
        "citation_authorization": CITATION_CASES,
        "citation_hash_match": CITATION_CASES,
        "citation_locator_match": CITATION_CASES,
        "citation_support": CITATION_CASES,
        "citation_completeness": CITATION_CASES,
        "question_count_pass": GENERATION_CASES,
        "requested_question_count": GENERATION_CASES,
        "generated_question_count": GENERATION_CASES,
        "correct_refusal": GENERATION_CASES,
        "unsupported_generation_rate": GENERATION_CASES,
        "answerable_refusal_rate": GENERATION_CASES,
        "question_schema_pass": GENERATION_CASES,
        "duplicate_question_rate": GENERATION_CASES,
        "answer_correctness": GENERATION_CASES,
        "source_support": GENERATION_CASES,
        "solvability": GENERATION_CASES,
        "explanation_correctness": GENERATION_CASES,
        "scope_compliance": GENERATION_CASES,
        "stem_premise_support": GENERATION_CASES,
        "internal_candidate_validity": GENERATION_CASES,
        "valid_question_yield": GENERATION_CASES,
        "full_set_pass": GENERATION_CASES,
        "objective_coverage": GENERATION_CASES,
        "cost_per_valid_question_cny": GENERATION_CASES,
        "distractor_quality": frozenset({"quiz"}),
        "ragas_faithfulness": frozenset({"quiz"}),
        "qa_correctness": QA_CASES,
        "qa_faithfulness": QA_CASES,
        "qa_answer_status_match": QA_CASES,
        "qa_failure_behavior_match": QA_CASES,
        "qa_answer_structure_validity": QA_CASES,
        "qa_citation_validity": QA_CASES,
        "qa_fact_citation_coverage": QA_CASES,
        "qa_evidence_group_recall": QA_CASES,
        "qa_all_evidence_hit": QA_CASES,
        "authorization_safety": POLICY_CASES,
        "production_isolation": POLICY_CASES,
        "revocation_safety": POLICY_CASES,
        "policy_expected_result": POLICY_CASES,
        "practice_outcome_match": PRACTICE_CASES,
        "practice_failure_behavior_match": PRACTICE_CASES,
        "practice_identity_match": PRACTICE_CASES,
        "grading_status_match": GRADING_CASES,
        "grading_abs_error": GRADING_CASES,
        "grading_false_accept_rate": GRADING_CASES,
        "grading_review_rate": GRADING_CASES,
        "grading_failure_rate": GRADING_CASES,
        "grading_failure_behavior_match": GRADING_CASES,
        "grading_identity_match": GRADING_CASES,
        "confirmation_policy_pass": GRADING_CASES,
        "learning_evidence_eligible": GRADING_CASES,
    }
)


def metric_applies(name: str, case_type: str) -> bool:
    """Return registered applicability; unknown names/cases are configuration errors."""
    if not isinstance(case_type, str) or case_type not in CASE_TYPES:
        raise ValueError(f"unknown evaluation case_type: {case_type!r}")
    if not isinstance(name, str) or name not in METRIC_CASE_TYPES:
        raise ValueError(f"unregistered evaluation metric: {name!r}")
    return case_type in METRIC_CASE_TYPES[name]
