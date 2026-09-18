"""Server-frozen call limits shared by the graph and durable provider meter."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.core.values import digest, dump
from app.models.teaching_quality import TeachingMode
from app.rag.contracts import BudgetLimits, Contract
from app.teaching.contracts import TeachSourcePolicy

POLICY_VERSION = "course-teaching-v1"


class TeachingPolicy(Contract):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    version: Literal["course-teaching-v1"] = POLICY_VERSION
    kind: Literal["outline", "lesson"]
    source_policy: TeachSourcePolicy
    mode: TeachingMode
    review_enabled: bool
    max_llm_calls: int = Field(ge=2, le=5)
    max_repair_calls: Literal[1] = 1
    max_review_calls: Literal[0, 2] = 2
    max_reranker_calls: Literal[0, 1] = 1
    generation_input_limit: Literal[12000] = 12000
    review_input_limit: Literal[16000] = 16000
    repair_input_limit: Literal[16000] = 16000
    review_output_limit: Literal[1200] = 1200
    max_input_tokens: Literal[60000, 72000] = 72000
    max_output_tokens: Literal[12000] = 12000
    review_timeout_seconds: int = Field(default=60, ge=1, le=120)
    repair_timeout_seconds: int = Field(default=90, ge=1, le=90)
    publication_reserve_seconds: int = Field(default=5, ge=1, le=30)

    @model_validator(mode="after")
    def fixed_caps(self):
        expected_llm = (4 if self.kind == "outline" else 5) if self.review_enabled else (2 if self.kind == "outline" else 3)
        if (
            self.max_llm_calls != expected_llm
            or self.max_review_calls != (2 if self.review_enabled else 0)
            or self.max_input_tokens != (72000 if self.review_enabled else 60000)
            or self.max_reranker_calls != int(self.kind == "lesson" and self.source_policy == "strict_docs")
            or (self.mode == "guided" and not self.review_enabled)
        ):
            raise ValueError("teaching_policy_invalid")
        return self

    @property
    def policy_hash(self):
        return digest(dump(self))

    @property
    def generation_output_limit(self):
        return 3000 if self.kind == "outline" else 4500

    def budget_limits(self, remaining_seconds):
        return BudgetLimits(
            max_llm_calls=self.max_llm_calls, max_reranker_calls=self.max_reranker_calls,
            max_search_calls=0, max_fetch_calls=0,
            max_input_tokens=self.max_input_tokens, max_output_tokens=self.max_output_tokens,
            deadline_seconds=max(.001, min(1800, remaining_seconds)),
        )


def freeze_teaching_policy(kind, mode, request_quality_review, source_policy, *, settings=None) -> TeachingPolicy:
    review = mode == "guided" or request_quality_review
    options = {}
    if settings is not None:
        for field in ("review_timeout_seconds", "repair_timeout_seconds", "publication_reserve_seconds"):
            options[field] = getattr(settings, "course_teaching_" + field)
    return TeachingPolicy(
        kind=kind, source_policy=source_policy, mode=mode, review_enabled=review,
        max_llm_calls=(4 if kind == "outline" else 5) if review else (2 if kind == "outline" else 3),
        max_review_calls=2 if review else 0,
        max_reranker_calls=int(kind == "lesson" and source_policy == "strict_docs"),
        max_input_tokens=72000 if review else 60000, **options,
    )


def validate_frozen_policy(request, *, kind, source_policy) -> TeachingPolicy:
    raw = request.get("teaching_policy")
    if raw is None:
        # Compatibility is only for already-queued requests without an agent mode.
        if request.get("teaching_mode", "fast") != "fast" or request.get("request_quality_review", False):
            raise ValueError("teaching_policy_missing")
        return freeze_teaching_policy(kind, "fast", False, source_policy)
    policy = TeachingPolicy.model_validate(raw)
    if (
        request.get("teaching_policy_hash") != policy.policy_hash
        or policy.kind != kind or policy.source_policy != source_policy
    ):
        raise ValueError("teaching_policy_invalid")
    return policy


def policy_from_job(job) -> TeachingPolicy:
    kind = {"course_outline": "outline", "course_lesson": "lesson"}.get(job["kind"])
    if kind is None or job["mode"] != "production":
        raise ValueError("teaching_policy_invalid")
    request = job["request"]
    source = request.get("source_policy") or request.get("spec", {}).get("source_policy")
    if source is None:
        source = "strict_docs" if (job.get("scope") or {}).get("documents") else "topic"
    return validate_frozen_policy(request, kind=kind, source_policy=source)


def can_review(policy, budget) -> bool:
    usage = budget.snapshot()
    return (
        policy.review_enabled
        and budget.remaining_seconds >= policy.review_timeout_seconds + policy.publication_reserve_seconds
        and usage.llm_calls + 1 <= policy.max_llm_calls
        and usage.input_tokens + policy.review_input_limit <= policy.max_input_tokens
        and usage.output_tokens + policy.review_output_limit <= policy.max_output_tokens
    )


def can_repair(policy, budget) -> bool:
    usage = budget.snapshot()
    remaining_calls = 2 if policy.review_enabled else 1
    time_needed = (
        policy.repair_timeout_seconds + policy.review_timeout_seconds + policy.publication_reserve_seconds
        if policy.review_enabled else policy.publication_reserve_seconds
    )
    return (
        budget.remaining_seconds >= time_needed
        and usage.llm_calls + remaining_calls <= policy.max_llm_calls
        and usage.input_tokens + policy.repair_input_limit + (policy.review_input_limit if policy.review_enabled else 0) <= policy.max_input_tokens
        and usage.output_tokens + policy.generation_output_limit + (policy.review_output_limit if policy.review_enabled else 0) <= policy.max_output_tokens
    )
