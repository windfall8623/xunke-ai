"""Owner-specific grading snapshots and runtime fences, without provider calls."""

import json
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.core.values import dump, load, now
from app.llm.configuration import LLMConfig, resolve_llm_config
from app.practice.contracts import ShortAnswerQuestion
from app.practice.grade_contracts import GradeInputSnapshot
from app.practice.grade_provider import LangChainShortAnswerProvider
from app.practice.grading_config import (
    grading_model_configuration,
    grading_model_configuration_from_config,
)
from app.prompts.practice_grade_prompt import GRADER_VERSION, PROMPT_HASH, PROMPT_VERSION
from app.rag.contracts import DocumentEvidence, stable_hash, text_hash
from app.services import practice_grading_service as grading
from app.services import user_llm_config_service as configs
from app.workers.practice_grading_job import run_practice_grading


def user_config(**changes):
    return replace(LLMConfig("openai_compatible", "owner-model", "https://owner.invalid/v1",
                             "sk-owner-secret", source="user"), **changes)


@pytest.fixture
def settings(monkeypatch):
    value = Settings(_env_file=None, deepseek_api_key="sk-system-secret",
                     practice_enabled=True, practice_short_answer_enabled=True,
                     practice_grading_output_tokens=1234, practice_grading_context_window=16384)
    monkeypatch.setattr("app.practice.grading_config.get_settings", lambda: value)
    return value


@pytest.fixture
def snapshot(settings):
    question = ShortAnswerQuestion(
        id="question1", stem="Explain", difficulty="easy", concept_ids=["concept1"],
        citation_refs=["evidence1"], support_quotes=["Support"],
        rubric={"reference_answer": "Answer", "explanation": "Explanation", "criteria": [
            {"criterion_id": "criterion1", "reference_point": "First", "weight": "0.5", "evidence_refs": ["evidence1"]},
            {"criterion_id": "criterion2", "reference_point": "Second", "weight": "0.5", "evidence_refs": ["evidence1"]},
        ]},
    )
    evidence = DocumentEvidence(
        evidence_id="evidence1", owner_id=17, namespace="production", title="Title",
        excerpt="Support", text_hash=text_hash("Support"), doc_id="doc1",
        document_version_id="version1", parse_artifact_id="parse1", index_build_id="build1",
        attempt_id="indexattempt1", chunk_id="chunk1",
        locator={"parse_artifact_id": "parse1", "start_char": 0, "end_char": 7, "quote_hash": text_hash("Support"),
                 "source_sha256": "d" * 64, "canonical_text_hash": "e" * 64,
                 "parser_version": "parser1", "normalizer_version": "normalizer1", "block_id": "block1"},
    )
    return GradeInputSnapshot(
        owner_id=17, mode="production", run_id="run1", attempt_id="attempt1",
        grading_request_id="grade1", space_id="space1", scope_revision=1,
        scope_fingerprint="a" * 64, question=question, answer={"text": "My answer"},
        question_version="b" * 64, rubric_version=question.rubric.version,
        rubric_hash="c" * 64, response_hash=stable_hash({"type": "short_answer", "text": "My answer"}),
        evidence=[evidence], help_usage="none",
        model_fingerprint=stable_hash(grading_model_configuration_from_config(user_config(), settings)),
        prompt_hash=PROMPT_HASH, prompt_version=PROMPT_VERSION, grader_version=GRADER_VERSION,
    )


def test_production_fingerprint_matches_adapter_and_excludes_keys(settings):
    config = user_config()
    metadata = grading_model_configuration_from_config(config, settings)
    provider = LangChainShortAnswerProvider(
        SimpleNamespace(ainvoke=AsyncMock(), max_tokens=1234), model_configuration=metadata,
        output_token_limit=settings.practice_grading_output_tokens,
        model_context_window=settings.practice_grading_context_window,
    )
    assert provider.model_configuration == metadata
    assert provider.model_fingerprint == stable_hash(metadata)
    assert metadata["config_source"] == "user"
    assert metadata["endpoint_hash"] == text_hash(config.base_url)
    assert set(metadata) == {"provider", "model", "endpoint_hash", "temperature", "config_source",
                             "output_token_limit", "model_context_window", "max_retries"}
    assert config.api_key not in json.dumps(metadata)
    assert config.base_url not in json.dumps(metadata)
    assert metadata == grading_model_configuration_from_config(user_config(api_key="rotated-secret"), settings)


def test_evaluation_system_identity_remains_frozen(settings):
    config = resolve_llm_config(settings)
    assert grading_model_configuration(settings) == {
        "provider": config.provider, "model": config.model, "endpoint_hash": text_hash(config.base_url),
        "temperature": 0.2, "output_token_limit": 1234, "model_context_window": 16384, "max_retries": 0,
    }
    assert "config_source" not in grading_model_configuration(settings)


@pytest.mark.parametrize("field,value", [
    ("model", "changed"), ("provider", "anthropic"), ("endpoint_hash", "0" * 64),
    ("temperature", 0.3), ("output_token_limit", 1000), ("model_context_window", 9999),
    ("config_source", "system"), ("max_retries", 1),
])
def test_current_grader_rejects_changed_identity(snapshot, settings, field, value):
    metadata = grading_model_configuration_from_config(user_config(), settings)
    grading.require_current_grader(snapshot, metadata)
    with pytest.raises(AppError) as error:
        grading.require_current_grader(snapshot, metadata | {field: value})
    assert error.value.code == "grading_configuration_changed"


def test_current_grader_rejects_system_and_prompt_drift(snapshot, settings):
    with pytest.raises(AppError):
        grading.require_current_grader(snapshot, grading_model_configuration(settings))
    for field in ("prompt_hash", "prompt_version", "grader_version"):
        with pytest.raises(AppError):
            grading.require_current_grader(snapshot.model_copy(update={field: "changed"}),
                                           grading_model_configuration_from_config(user_config(), settings))


@pytest.mark.asyncio
async def test_missing_user_config_never_falls_back(settings, monkeypatch):
    monkeypatch.setattr(configs, "get_actor_role", AsyncMock(return_value="learner"))
    monkeypatch.setattr(configs, "get_user_llm_config", AsyncMock(return_value=None))
    conn = object()
    with pytest.raises(AppError) as error:
        await grading.current_grader_configuration(17, settings, conn=conn)
    assert error.value.code == "llm_configuration_required"
    configs.get_user_llm_config.assert_awaited_once_with(17, conn=conn)


@pytest.mark.asyncio
async def test_own_failure_propagates_and_incomplete_config_is_explicit(settings, monkeypatch):
    resolver = AsyncMock(side_effect=AppError(422, "user_llm_key_unavailable", "Unavailable"))
    monkeypatch.setattr(configs, "resolve_actor_llm_config", resolver)
    with pytest.raises(AppError) as error:
        await grading.current_grader_configuration(17, settings)
    assert error.value.code == "user_llm_key_unavailable"
    resolver.side_effect = None
    resolver.return_value = user_config(api_key="")
    with pytest.raises(AppError) as error:
        await grading.current_grader_configuration(17, settings)
    assert error.value.code == "llm_configuration_required"


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_connection", [False, True])
async def test_authorization_resolves_before_locks_and_reuses_transaction(snapshot, settings, monkeypatch, existing_connection):
    order, conn = [], object()
    job = {"user_id": 17, "request": {}}
    state = grading.GradingState({}, None, None, {}, snapshot, {}, None)

    async def resolve(owner_id, settings=None, *, conn=None):
        order.append(("resolve", conn))
        assert owner_id == 17
        return user_config()

    @asynccontextmanager
    async def transaction():
        order.append(("transaction", conn))
        yield conn

    async def locked(job, connection):
        order.append(("lock", connection))
        return job

    monkeypatch.setattr(configs, "resolve_actor_llm_config", resolve)
    monkeypatch.setattr(grading, "transaction", transaction)
    monkeypatch.setattr(grading.job_service, "locked_job", locked)
    monkeypatch.setattr(grading, "task_request", lambda raw: SimpleNamespace(attempt_id="attempt1"))
    monkeypatch.setattr(grading, "locked_grading_state", AsyncMock(return_value=state))
    monkeypatch.setattr(grading, "require_grading_job", lambda *args, **kwargs: None)
    result = await grading.authorize_grading_execution(job, conn=conn if existing_connection else None)
    assert order[0] == ("resolve", conn if existing_connection else None)
    assert [item[0] for item in order] == (["resolve", "lock"] if existing_connection else ["resolve", "transaction", "lock"])
    assert result.model_configuration == grading_model_configuration_from_config(user_config(), settings)
    assert user_config().api_key not in repr(result)


@pytest.mark.asyncio
async def test_submission_seals_user_snapshot_without_credentials(snapshot, settings, monkeypatch):
    conn = SimpleNamespace(get_transaction_status=lambda: True)
    actor = SimpleNamespace(owner_id=17)
    practice = {"practice_id": "practice1", "space_id": "space1", "scope_revision": 1}
    request = SimpleNamespace(spec=SimpleNamespace(space_id="space1", scope_revision=1), scope_fingerprint=snapshot.scope_fingerprint)
    artifact = SimpleNamespace(question_versions={"question1": snapshot.question_version},
        rubric_hashes={"question1": snapshot.rubric_hash},
        evidence_pack=SimpleNamespace(evidence=snapshot.evidence, resolved_scope=SimpleNamespace(model_dump=lambda **kwargs: {})))
    attempt = {"origin_kind": "practice", "origin_id": "practice1", "question_id": "question1", "space_id": "space1",
        "scope_revision": 1, "question_version": snapshot.question_version, "response_hash": snapshot.response_hash,
        "answer_json": dump(snapshot.answer), "help_usage": "none"}
    persisted = {}

    async def fetch(sql, args, *, conn):
        if "FROM learning_attempts" in sql:
            return attempt
        if "SELECT grading_request_id,active_task_id" in sql:
            return None
        return {"request_json": persisted["json"]}

    async def execute(sql, args, *, conn):
        if "INSERT INTO practice_grading_requests" in sql:
            persisted["json"] = args[-1]
        if "SET request_hash=" in sql:
            persisted["hash"] = args[0]
        return 1

    resolver = AsyncMock(return_value=user_config())
    monkeypatch.setattr(configs, "resolve_actor_llm_config", resolver)
    monkeypatch.setattr(grading, "fetch_one", fetch)
    monkeypatch.setattr(grading, "execute", execute)
    monkeypatch.setattr(grading, "load_grading_profile", lambda: None)
    monkeypatch.setattr(grading.job_service, "enqueue_job", AsyncMock(return_value={"task_id": "task1"}))
    grade_id, task_id = await grading.queue_short_answer(conn, actor, practice=practice, request=request,
        artifact=artifact, question=snapshot.question, attempt_id="attempt1")
    frozen = GradeInputSnapshot.model_validate(load(persisted["json"]))
    assert frozen.model_fingerprint == snapshot.model_fingerprint
    assert frozen.owner_id == 17 and frozen.grading_request_id == grade_id and task_id == "task1"
    assert persisted["hash"] == stable_hash(frozen.model_dump(mode="json"))
    assert "sk-owner-secret" not in persisted["json"] and "sk-system-secret" not in persisted["json"]
    resolver.assert_awaited_once_with(17, settings=None, conn=conn)


@pytest.mark.asyncio
async def test_retry_cannot_change_frozen_model(snapshot, settings, monkeypatch):
    state = grading.GradingState({}, None, None, {"status": "failed"}, snapshot, {}, None)
    conn = object()

    @asynccontextmanager
    async def transaction():
        yield conn

    monkeypatch.setattr(grading, "transaction", transaction)
    monkeypatch.setattr(grading, "locked_grading_state", AsyncMock(return_value=state))
    monkeypatch.setattr(grading, "fetch_one", AsyncMock(return_value=None))
    monkeypatch.setattr(configs, "resolve_actor_llm_config", AsyncMock(return_value=user_config(model="changed")))
    enqueue = AsyncMock()
    monkeypatch.setattr(grading.job_service, "enqueue_job", enqueue)
    with pytest.raises(AppError) as error:
        await grading._retry_once(SimpleNamespace(owner_id=17), "attempt1", "retry1")
    assert error.value.code == "grading_configuration_changed"
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_worker_rejects_system_provider_for_user_snapshot(snapshot, settings, monkeypatch):
    metadata = grading_model_configuration_from_config(user_config(), settings)
    state = grading.GradingState({}, None, None, {}, snapshot, {}, None, metadata)
    monkeypatch.setattr(grading, "authorize_grading_execution", AsyncMock(return_value=state))
    provider = SimpleNamespace(model_fingerprint=stable_hash(grading_model_configuration(settings)),
        output_token_limit=1234, model_context_window=16384, grade=AsyncMock())
    with pytest.raises(AppError) as error:
        await run_practice_grading({}, SimpleNamespace(owner_id=17), None, provider=provider, usage_loader=None)
    assert error.value.code == "grading_configuration_changed"
    provider.grade.assert_not_called()


@pytest.mark.asyncio
async def test_worker_uses_authorized_owner_bounds_before_provider_call(snapshot, settings, monkeypatch):
    from app.workers import practice_grading_job as worker

    metadata = grading_model_configuration_from_config(user_config(), settings)
    scope = SimpleNamespace(namespace="production")
    state = grading.GradingState({}, None, scope, {}, snapshot, {}, None, metadata)
    auth = AsyncMock(return_value=state)
    monkeypatch.setattr(grading, "authorize_grading_execution", auth)
    conn = object()

    @asynccontextmanager
    async def transaction():
        yield conn

    class StopBeforeProvider(Exception):
        pass

    async def grade(frozen, actor, context, resolved_scope, ports, *, profile):
        assert frozen == snapshot and resolved_scope is scope
        assert context.budget.max_output_tokens == 1234 * 2
        assert context.budget.max_input_tokens == 16384 * 2
        assert await ports.reauthorize(scope) is scope
        raise StopBeforeProvider()

    monkeypatch.setattr(worker, "transaction", transaction)
    monkeypatch.setattr(worker, "execute", AsyncMock())
    monkeypatch.setattr(worker, "grade_short_answer", grade)
    monkeypatch.setattr(worker.job_service, "heartbeat", AsyncMock())
    monkeypatch.setattr(grading, "current_snapshot_profile", lambda frozen: None)
    provider = SimpleNamespace(model_fingerprint=snapshot.model_fingerprint,
        output_token_limit=1234, model_context_window=16384, grade=AsyncMock(), measure_input_tokens=lambda *args: 1)
    job = {"task_id": "task1", "deadline_at": now() + timedelta(seconds=30)}
    with pytest.raises(StopBeforeProvider):
        await worker.run_practice_grading(job, SimpleNamespace(owner_id=17),
            SimpleNamespace(verify_evidence=AsyncMock()), provider=provider, usage_loader=None)
    assert auth.await_count == 3
    assert auth.await_args_list[1].kwargs == {"conn": conn}
    provider.grade.assert_not_called()
