"""Read-only teaching readiness and host-owned frozen generation metadata."""

from app.core.config import get_settings
from app.core.db import fetch_all
from app.core.errors import AppError
from app.core.values import load
from app.llm.configuration import resolve_llm_config
from app.models.teaching_quality import CourseCapabilities
from app.rag.contracts import text_hash
from app.teaching.policy import TeachingPolicy, freeze_teaching_policy
from app.teaching.prompts import PROMPT_VERSION, teaching_skill
from app.teaching.protocol import V2

IDENTITY_FIELDS = ("provider", "model", "endpoint_hash")


async def capabilities():
    settings = get_settings()
    reason = None
    if not settings.course_enabled:
        reason = "course_disabled"
    elif not settings.enable_course_teaching_agents:
        reason = "teaching_agents_disabled"
    elif not resolve_llm_config(settings).configured:
        reason = "course_provider_unavailable"
    else:
        rows = await fetch_all(
            "SELECT status_json FROM worker_heartbeats WHERE role IN ('rag_owner','rag_generation') "
            "AND heartbeat_at>=UTC_TIMESTAMP(6)-INTERVAL 90 SECOND",
        )
        if not any(load(row["status_json"], {}).get("teaching_agents_ready") is True for row in rows):
            reason = "teaching_agents_not_ready"
    return CourseCapabilities(
        teaching_modes=["fast", "guided"] if reason is None else ["fast"],
        unavailable_reason=reason,
    ).model_dump(mode="json")


async def require_teaching_available(mode, request_quality_review, *, schema_version=V2):
    if mode != "guided" and not request_quality_review:
        return
    if schema_version != V2:
        raise AppError(409, "course_quality_unavailable", "旧版课程保留原有生成方式，暂不支持教学核对")
    if "guided" not in (await capabilities())["teaching_modes"]:
        raise AppError(409, "teaching_agents_unavailable", "协作教学暂未就绪，请选择快速生成或稍后重试")


def frozen_request_fields(kind, spec, *, request_quality_review=None, inherited=None):
    """Only the server builds this envelope; the public request has no policy field."""
    settings = get_settings()
    mode = spec.teaching_mode
    requested = spec.request_quality_review if request_quality_review is None else request_quality_review
    policy = freeze_teaching_policy(kind, mode, requested, spec.source_policy, settings=settings)
    if inherited and inherited.get("teaching_policy"):
        old_policy = TeachingPolicy.model_validate(inherited["teaching_policy"])
        policy = TeachingPolicy.model_validate({
            **policy.model_dump(mode="json"),
            **{field: getattr(old_policy, field) for field in (
                "review_timeout_seconds", "repair_timeout_seconds", "publication_reserve_seconds",
            )},
        })
    config = resolve_llm_config(settings)
    skill = teaching_skill()
    from app.teaching.reviewer import REVIEWER_PROMPT_VERSION

    metadata = {
        "teaching_model": {"provider": config.provider, "model": config.model,
                           "endpoint_hash": text_hash(config.base_url)},
        "skill_hash": skill["hash"], "skill_version": skill["version"],
        "teaching_prompt_version": PROMPT_VERSION,
        "reviewer_prompt_version": REVIEWER_PROMPT_VERSION,
    }
    if inherited:
        for field in metadata:
            if field in inherited:
                metadata[field] = inherited[field]
    return {
        "teaching_mode": mode, "request_quality_review": requested,
        "source_policy": spec.source_policy,
        "teaching_policy": policy.model_dump(mode="json"), "teaching_policy_hash": policy.policy_hash,
        **metadata,
    }


def require_frozen_runtime(job, generator, policy):
    request = job["request"]
    frozen = request.get("teaching_model")
    if frozen is not None:
        actual = {key: generator.model_configuration.get(key) for key in IDENTITY_FIELDS}
        if frozen != actual:
            raise AppError(409, "teaching_policy_changed", "课程模型配置已变化，请显式重试任务")
    from app.teaching.reviewer import REVIEWER_PROMPT_VERSION

    for field, actual in (
        ("skill_hash", generator.skill["hash"]), ("skill_version", generator.skill["version"]),
        ("teaching_prompt_version", PROMPT_VERSION), ("reviewer_prompt_version", REVIEWER_PROMPT_VERSION),
    ):
        if field in request and request[field] != actual:
            raise AppError(409, "teaching_policy_changed", "教学规范已变化，请显式重试任务")
    if policy.review_enabled:
        reviewer = generator.reviewer
        if reviewer is None:
            raise AppError(409, "teaching_agents_unavailable", "教学核对适配器尚未就绪")
        if frozen is not None and {key: reviewer.model_configuration.get(key) for key in IDENTITY_FIELDS} != frozen:
            raise AppError(409, "teaching_policy_changed", "教学核对模型配置已变化，请显式重试任务")
