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


@pytest.fixture
def personal_teaching(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.core.config import Settings
    from app.core.values import dump
    from app.llm.configuration import LLMConfig
    from app.services import course_teaching, user_llm_config_service

    settings = Settings(_env_file=None, course_enabled=True, enable_course_teaching_agents=True,
                        deepseek_api_key="", llm_api_key="", anthropic_api_key="", llm_provider="deepseek",
                        enable_course_revisions=True)
    personal = LLMConfig("openai_compatible", "personal-model", "https://personal.example/v1",
                         "synthetic-private-key", source="user")
    role = AsyncMock(return_value="learner")
    stored = AsyncMock(return_value={"provider": personal.provider, "model": personal.model,
                                     "base_url": personal.base_url, "api_key_cipher": "synthetic-cipher"})
    monkeypatch.setattr(course_teaching, "get_settings", lambda: settings)
    monkeypatch.setattr(user_llm_config_service, "get_settings", lambda: settings)
    monkeypatch.setattr(user_llm_config_service, "get_actor_role", role)
    monkeypatch.setattr(user_llm_config_service, "get_user_llm_config", stored)
    monkeypatch.setattr(user_llm_config_service, "decrypt_api_key", lambda *args: personal.api_key)
    monkeypatch.setattr(course_teaching, "fetch_all", AsyncMock(return_value=[
        {"status_json": dump({"teaching_agents_ready": True})},
    ]))
    return SimpleNamespace(settings=settings, config=personal, role=role, stored=stored, service=course_teaching)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["learner", "evaluator"])
async def test_personal_teaching_readiness_and_frozen_identity_do_not_need_system_model(personal_teaching, role):
    from app.core.values import dump
    from app.models.course import CourseCreate
    from app.rag.contracts import text_hash

    fixture = personal_teaching
    fixture.role.return_value = role
    capabilities = await fixture.service.capabilities(7)
    assert capabilities == {"teaching_modes": ["fast", "guided"], "unavailable_reason": None}
    await fixture.service.require_teaching_available("guided", False, owner_id=7)
    spec = CourseCreate(topic="Synthetic topic", teaching_mode="guided")
    request = await fixture.service.frozen_request_fields("outline", spec, owner_id=7)
    assert request["teaching_model"] == {
        "provider": "openai_compatible", "model": "personal-model",
        "endpoint_hash": text_hash(fixture.config.base_url), "config_source": "user",
    }
    assert fixture.config.api_key not in dump(request) and fixture.config.base_url not in dump(request)
    fixture.stored.assert_awaited()
    assert all(call.args[0] == 7 for call in fixture.role.await_args_list)


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["learner", "evaluator"])
@pytest.mark.parametrize("mode", ["fast", "guided"])
async def test_missing_personal_model_blocks_queue_even_if_system_is_configured(personal_teaching, monkeypatch, role, mode):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.core.errors import AppError
    from app.models.course import CourseCreate
    from app.services import course_service

    fixture = personal_teaching
    fixture.settings.deepseek_api_key = "synthetic-system-key"
    fixture.role.return_value = role
    fixture.stored.return_value = None
    monkeypatch.setattr(course_service, "get_settings", lambda: fixture.settings)
    enqueue = AsyncMock(side_effect=AssertionError("No job without personal configuration"))
    monkeypatch.setattr(course_service.job_service, "enqueue_job", enqueue)
    result = await fixture.service.capabilities(7)
    assert result["teaching_modes"] == ["fast"] and result["unavailable_reason"] == "llm_configuration_required"
    with pytest.raises(AppError) as error:
        await course_service.create_course(SimpleNamespace(owner_id=7), CourseCreate(topic="Synthetic", teaching_mode=mode), "key")
    assert error.value.code == "llm_configuration_required"
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_readiness_uses_only_system_even_when_personal_config_exists(personal_teaching):
    from app.core.errors import AppError
    from app.models.course import CourseCreate

    fixture = personal_teaching
    fixture.role.return_value = "admin"
    assert (await fixture.service.capabilities(7))["unavailable_reason"] == "course_provider_unavailable"
    with pytest.raises(AppError) as error:
        await fixture.service.frozen_request_fields("outline", CourseCreate(topic="Synthetic"), owner_id=7)
    assert error.value.code == "course_provider_unavailable"
    fixture.stored.assert_not_awaited()
    fixture.settings.deepseek_api_key = "synthetic-system-key"
    assert (await fixture.service.capabilities(7))["teaching_modes"] == ["fast", "guided"]
    fields = await fixture.service.frozen_request_fields("outline", CourseCreate(topic="Synthetic"), owner_id=7)
    assert fields["teaching_model"]["config_source"] == "system"
    fixture.stored.assert_not_awaited()


@pytest.mark.asyncio
async def test_preload_inherits_personal_identity_and_runtime_rejects_system_reviewer(personal_teaching):
    from types import SimpleNamespace

    from app.core.errors import AppError
    from app.models.course import CourseCreate
    from app.teaching.policy import policy_from_job
    from app.teaching.prompts import teaching_skill

    fixture = personal_teaching
    spec = CourseCreate(topic="Synthetic", teaching_mode="guided")
    fields = await fixture.service.frozen_request_fields("outline", spec, owner_id=7)
    fixture.role.reset_mock()
    fixture.stored.return_value = None  # preload inherits, but execution still resolves afresh
    lesson = await fixture.service.frozen_request_fields("lesson", spec, owner_id=7, inherited=fields)
    assert lesson["teaching_model"] == fields["teaching_model"]
    fixture.role.assert_not_awaited()
    job = {"kind": "course_lesson", "mode": "production", "request": lesson}
    policy = policy_from_job(job)
    generator = SimpleNamespace(model_configuration=fields["teaching_model"], skill=teaching_skill(),
                                reviewer=SimpleNamespace(model_configuration=fields["teaching_model"]))
    fixture.service.require_frozen_runtime(job, generator, policy)
    generator.reviewer.model_configuration = {**fields["teaching_model"], "config_source": "system"}
    with pytest.raises(AppError) as mismatch:
        fixture.service.require_frozen_runtime(job, generator, policy)
    assert mismatch.value.code == "teaching_policy_changed"
    generator.reviewer.model_configuration = fields["teaching_model"]
    generator.model_configuration = {**fields["teaching_model"], "config_source": "system"}
    with pytest.raises(AppError):
        fixture.service.require_frozen_runtime(job, generator, policy)


@pytest.mark.asyncio
async def test_legacy_main_teaching_identity_stays_readable(personal_teaching):
    from types import SimpleNamespace

    from app.models.course import CourseCreate
    from app.teaching.policy import policy_from_job
    from app.teaching.prompts import teaching_skill

    fixture = personal_teaching
    fields = await fixture.service.frozen_request_fields("outline", CourseCreate(topic="Synthetic"), owner_id=7)
    identity = fields["teaching_model"]
    fields["teaching_model"] = {key: value for key, value in identity.items() if key != "config_source"}
    job = {"kind": "course_outline", "mode": "production", "request": fields}
    generator = SimpleNamespace(model_configuration=identity, skill=teaching_skill(), reviewer=None)
    fixture.service.require_frozen_runtime(job, generator, policy_from_job(job))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["course_application_generate", "course_application_feedback"])
async def test_application_prequeue_uses_personal_configuration_and_keeps_replay_readable(
    personal_teaching, monkeypatch, kind,
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.core.errors import AppError
    from app.rag.contracts import ResolvedScope
    from app.services import course_application_service as application, course_service

    fixture = personal_teaching
    fixture.settings.deepseek_api_key = "synthetic-system-key"
    fixture.stored.return_value = None
    monkeypatch.setattr(course_service, "get_settings", lambda: fixture.settings)
    monkeypatch.setattr(application.assessments, "authorized_assessment", AsyncMock(return_value=(
        {}, {"application_generation_task_id": None, "completed_at": None, "snapshot_json": "{}"},
        ResolvedScope(owner_id=7, namespace="production"),
    )))
    monkeypatch.setattr(application, "owned_attempt", AsyncMock(return_value={"feedback_task_id": None}))
    old = AsyncMock(return_value=None)
    monkeypatch.setattr(application.job_service, "existing_job", old)
    monkeypatch.setattr(application.assessments, "task_summary", AsyncMock(return_value=None))
    monkeypatch.setattr(application, "application_criterion_ids", lambda _: ["criterion-1"])
    queue = AsyncMock(side_effect=AssertionError("No queue or system fallback"))
    monkeypatch.setattr(application.job_service, "enqueue_job", queue)
    actor = SimpleNamespace(owner_id=7)
    invoke = (
        lambda: application.create_application_job(actor, "course", "assessment", "key")
    ) if kind.endswith("generate") else (
        lambda: application.create_feedback_job(actor, "course", "assessment", "attempt", "key")
    )
    with pytest.raises(AppError) as missing:
        await invoke()
    assert missing.value.code == "llm_configuration_required"
    queue.assert_not_awaited()
    old.return_value = {"task_id": "saved-task"}
    monkeypatch.setattr(application.assessments, "get_course_assessment", AsyncMock(return_value={"saved": True}))
    monkeypatch.setattr(application, "get_application_attempt", AsyncMock(return_value={"saved": True}))
    assert await invoke() == {"saved": True}
    queue.assert_not_awaited()


@pytest.mark.asyncio
async def test_revision_queue_uses_saved_preview_fields_and_blocks_missing_personal_config(personal_teaching, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.core.errors import AppError
    from app.core.values import dump
    from app.models.course import CourseRevisionGenerate
    from app.services import course_revision_service as revisions, course_service

    fixture = personal_teaching
    monkeypatch.setattr(course_service, "get_settings", lambda: fixture.settings)
    row = {"status": "preview", "revision": 2, "expected_course_revision": 7,
           "instruction": "Saved instruction", "selection_json": dump({"lessons": [
               {"lesson_id": "lesson", "expected_content_version": 1, "instruction": "Saved lesson instruction"},
           ]})}
    monkeypatch.setattr(revisions, "_owned_request", AsyncMock(return_value=row))
    monkeypatch.setattr(revisions, "_request_view", lambda value: value)
    writes, generate = AsyncMock(), AsyncMock(return_value={"task_id": "candidate-task"})
    monkeypatch.setattr(revisions, "execute", writes)
    monkeypatch.setattr(course_service, "generate_lesson", generate)
    body = CourseRevisionGenerate(revision_id="revision", expected_revision=2)
    fixture.stored.return_value = None
    with pytest.raises(AppError) as missing:
        await revisions.start_revision_jobs(SimpleNamespace(owner_id=7), "course", body, "key")
    assert missing.value.code == "llm_configuration_required"
    writes.assert_not_awaited()
    generate.assert_not_awaited()
    fixture.stored.return_value = {"provider": fixture.config.provider, "model": fixture.config.model,
                                  "base_url": fixture.config.base_url, "api_key_cipher": "synthetic-cipher"}
    await revisions.start_revision_jobs(SimpleNamespace(owner_id=7), "course", body, "key")
    request = generate.await_args.args[3]
    assert request.expected_course_revision == 7 and request.revision_id == "revision"
    assert "instruction=" not in writes.await_args.args[0]
    assert "revision=%s" in writes.await_args.args[0]
