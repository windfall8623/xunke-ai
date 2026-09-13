"""Frozen teaching budgets and reviewer results cannot silently widen authority."""

import copy

import pytest
from pydantic import ValidationError


@pytest.mark.parametrize("kind,mode,review,source,llm,rerank", [
    ("outline", "fast", False, "topic", 2, 0),
    ("lesson", "fast", False, "strict_docs", 3, 1),
    ("outline", "guided", False, "strict_docs", 4, 0),
    ("lesson", "guided", False, "strict_docs", 5, 1),
    ("lesson", "fast", True, "topic", 5, 0),
])
def test_mode_freezes_shared_call_caps(kind, mode, review, source, llm, rerank):
    from app.teaching.policy import freeze_teaching_policy

    policy = freeze_teaching_policy(kind, mode, review, source)
    assert policy.max_llm_calls == llm
    assert policy.max_reranker_calls == rerank
    assert policy.max_repair_calls == 1
    assert policy.review_enabled == (mode == "guided" or review)


def test_persisted_policy_cannot_be_rehashed_to_expand_a_budget():
    from app.core.values import digest, dump
    from app.teaching.policy import freeze_teaching_policy, validate_frozen_policy

    policy = freeze_teaching_policy("outline", "fast", False, "topic")
    raw = policy.model_dump(mode="json")
    raw["max_llm_calls"] = 5
    request = {"teaching_policy": raw, "teaching_policy_hash": digest(dump(raw))}
    with pytest.raises(ValueError):
        validate_frozen_policy(request, kind="outline", source_policy="topic")


def test_review_timeout_bounds_preserve_frozen_caps_and_remaining_deadline(monkeypatch):
    from types import SimpleNamespace

    from app.core.config import Settings
    from app.teaching.policy import (
        TeachingPolicy, can_repair, can_review, freeze_teaching_policy, validate_frozen_policy,
    )

    monkeypatch.delenv("COURSE_TEACHING_REVIEW_TIMEOUT_SECONDS", raising=False)
    options = dict(_env_file=None, app_env="test", redis_enabled=False,
                   vector_backend="chroma", query_embedding_cache_enabled=False)
    assert Settings(**options).course_teaching_review_timeout_seconds == 60
    default = freeze_teaching_policy("outline", "guided", False, "topic")
    assert default.review_timeout_seconds == 60
    for seconds in (1, 90, 120):
        settings = Settings(**options, course_teaching_review_timeout_seconds=seconds)
        policy = freeze_teaching_policy("outline", "guided", False, "topic", settings=settings)
        assert policy.review_timeout_seconds == seconds
        assert policy.model_dump(exclude={"review_timeout_seconds"}) == default.model_dump(
            exclude={"review_timeout_seconds"})
    for seconds in (0, 121):
        with pytest.raises(ValidationError):
            Settings(**options, course_teaching_review_timeout_seconds=seconds)
        with pytest.raises(ValidationError):
            TeachingPolicy.model_validate({**default.model_dump(), "review_timeout_seconds": seconds})

    old = TeachingPolicy.model_validate({**default.model_dump(), "review_timeout_seconds": 30})
    restored = validate_frozen_policy(
        {"teaching_policy": old.model_dump(mode="json"), "teaching_policy_hash": old.policy_hash},
        kind="outline", source_policy="topic",
    )
    assert restored.review_timeout_seconds == 30
    budget = SimpleNamespace(remaining_seconds=64.9, snapshot=lambda: SimpleNamespace(
        llm_calls=1, input_tokens=0, output_tokens=0))
    assert not can_review(default, budget)
    budget.remaining_seconds = 65
    assert can_review(default, budget)
    budget.remaining_seconds = 154.9
    assert not can_repair(default, budget)
    budget.remaining_seconds = 155
    assert can_repair(default, budget)
    assert default.budget_limits(100).deadline_seconds == 100


def test_reviewer_cannot_confirm_a_grade():
    from app.teaching.agents import require_role_tool

    with pytest.raises(ValueError, match="teaching_agent_tool_forbidden"):
        require_role_tool("reviewer", "confirm_assessment")


def passing_proposal():
    return {"dimensions": [
        {"dimension": "goal_alignment", "result": "pass"},
        {"dimension": "prerequisite_order", "result": "pass"},
        {"dimension": "example_correctness", "result": "pass"},
        {"dimension": "check_fit", "result": "pass"},
        {"dimension": "source_support", "result": "not_applicable"},
        {"dimension": "answer_leakage", "result": "pass"},
    ], "findings": []}


@pytest.mark.parametrize("invalid", ["missing_dimension", "duplicate_dimension", "fail_without_finding", "severity_downgrade"])
def test_reviewer_requires_complete_consistent_findings(invalid):
    from app.teaching.review_contracts import ReviewProposal

    raw = passing_proposal()
    if invalid == "missing_dimension":
        raw["dimensions"].pop()
    elif invalid == "duplicate_dimension":
        raw["dimensions"][1] = copy.deepcopy(raw["dimensions"][0])
    elif invalid == "fail_without_finding":
        raw["dimensions"][0]["result"] = "fail"
    else:
        raw["findings"].append({"code": "answer_leaked", "dimension": "answer_leakage", "severity": "suggestion",
                               "explanation": "检查泄漏答案", "suggestion": "移除答案"})
    with pytest.raises(ValidationError):
        ReviewProposal.model_validate(raw)
