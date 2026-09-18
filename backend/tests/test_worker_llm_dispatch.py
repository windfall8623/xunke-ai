"""No DB or provider network: production chat isolation at the worker boundary."""

import asyncio
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.core.errors import AppError
from app.llm.configuration import LLMConfig
from app.rag.engine import RagEngine
from app.workers import providers, rag_owner, user_dispatch


def config(owner, key=None, source="user"):
    return LLMConfig("openai_compatible", "model-" + owner,
                     "https://" + owner + ".example/v1", key or "secret-" + owner,
                     source=source)


class FakeModel:
    max_retries = 0

    def __init__(self, config, *, root=None, **kwargs):
        self.config = config
        self.model_name = config.model
        self.kwargs = kwargs
        self.root = root or self
        self.closed = False

    def bind(self, **kwargs):
        return FakeModel(self.config, root=self.root, **{**self.kwargs, **kwargs})

    def bind_tools(self, tools, **kwargs):
        return self.bind(tools=tools, **kwargs)


@pytest.fixture
def runtime(monkeypatch):
    settings = Settings(_env_file=None, course_enabled=True)
    monkeypatch.setattr(user_dispatch, "get_settings", lambda: settings)
    created = []

    def make(config, **kwargs):
        value = FakeModel(config, **kwargs)
        created.append(value)
        return value

    class Closer:
        def __init__(self, value):
            self.value = value

        async def aclose(self):
            self.value.closed = True

    monkeypatch.setattr(providers, "chat_model_from_config", make)
    monkeypatch.setattr(providers, "ChatModelCloser", Closer)
    engine = RagEngine(object(), object(), object(), lambda scope: scope,
                       reranker=object(), llm_reranker=object(),
                       web_provider=object(), qa_generator=object(), legacy_baseline=object())
    engine.requires_actor_llm = True
    worker = rag_owner.OwnerWorker(engine, report_generator=object())
    return worker, created


def adapters(worker):
    return [worker.engine.generator.llm, worker.report_generator.llm,
            worker.engine.qa_generator.llm, worker.engine.qa_generator.rewrite_llm,
            worker.engine.qa_generator.semantic_llm, worker.practice_provider.llm,
            worker.practice_provider.semantic_llm, worker.grading_provider.llm,
            worker.course_generator.outline_llm, worker.course_generator.lesson_llm,
            worker.course_tutor_generator.llm]


@pytest.mark.asyncio
async def test_overlapping_users_share_retrieval_not_models(runtime):
    worker, created = runtime
    calls = []

    async def resolve(owner_id, **kwargs):
        calls.append(owner_id)
        return config(owner_id)

    worker.runtime_resolver = resolve
    original = worker.engine.generator
    async with user_dispatch.isolated_dispatch(worker, {"mode": "production", "kind": "quiz"},
                                               SimpleNamespace(owner_id="alice")) as alice:
        async with user_dispatch.isolated_dispatch(worker, {"mode": "production", "kind": "qa"},
                                                   SimpleNamespace(owner_id="bob")) as bob:
            assert alice is not bob and alice.engine is not bob.engine
            assert worker.engine.generator is original
            for isolated, owner in ((alice, "alice"), (bob, "bob")):
                assert isolated.engine.store is worker.engine.store
                assert isolated.engine.embedding is worker.engine.embedding
                assert isolated.engine.retriever is worker.engine.retriever
                assert isolated.engine.web_provider is worker.engine.web_provider
                assert isolated.engine.legacy_baseline is None
                for adapter in adapters(isolated):
                    assert adapter.config_source == "user"
                    assert adapter.llm.config == config(owner)
                    assert not adapter.llm.root.closed
                for provider in (isolated.engine.qa_generator, isolated.practice_provider,
                                 isolated.grading_provider, isolated.course_generator,
                                 isolated.course_tutor_generator):
                    assert provider.model_configuration["config_source"] == "user"
                    assert "secret-" not in str(provider.model_configuration)
            assert not {id(x.llm.root) for x in adapters(alice)} & {
                id(x.llm.root) for x in adapters(bob)}
        assert all(adapter.llm.root.closed for adapter in adapters(bob))
        assert all(not adapter.llm.root.closed for adapter in adapters(alice))
    assert calls == ["alice", "bob"]
    assert all(model.closed for model in created)


@pytest.mark.asyncio
async def test_rotation_deletion_and_missing_config_never_reuse_default(runtime):
    worker, created = runtime
    current = config("alice", "old-secret")

    async def resolve(owner_id, **kwargs):
        if current is None:
            raise AppError(409, "llm_configuration_required", "Configuration required")
        return current

    worker.runtime_resolver = resolve
    job = {"mode": "production", "kind": "report", "request": {}}
    for key in ("old-secret", "rotated-secret"):
        current = config("alice", key)
        async with user_dispatch.isolated_dispatch(worker, job, SimpleNamespace(owner_id="alice")) as view:
            assert view.report_generator.llm.llm.config.api_key == key
        assert all(model.closed for model in created)
    count = len(created)
    current = None
    with pytest.raises(AppError, match="Configuration required") as caught:
        async with user_dispatch.isolated_dispatch(worker, job, SimpleNamespace(owner_id="alice")):
            pytest.fail("Deleted configuration must not dispatch")
    assert caught.value.code == "llm_configuration_required"
    assert len(created) == count
    assert job == {"mode": "production", "kind": "report", "request": {}}
    current = config("alice", " ")
    with pytest.raises(AppError) as caught:
        async with user_dispatch.isolated_dispatch(worker, job, SimpleNamespace(owner_id="alice")):
            pytest.fail("Unconfigured result must not dispatch")
    assert caught.value.code == "llm_configuration_required"
    assert len(created) == count


@pytest.mark.asyncio
async def test_admin_system_resolution_still_task_owned(runtime):
    worker, created = runtime

    async def resolve(owner_id, **kwargs):
        return config("admin", source="system")

    worker.runtime_resolver = resolve
    async with user_dispatch.isolated_dispatch(worker, {"mode": "production", "kind": "qa"},
                                               SimpleNamespace(owner_id="admin")) as view:
        assert all(adapter.config_source == "system" for adapter in adapters(view))
        assert view.engine.generator is not worker.engine.generator
    assert all(model.closed for model in created)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", sorted(user_dispatch.CHAT_JOB_KINDS))
async def test_managed_wrapper_routes_every_production_chat_kind(runtime, monkeypatch, kind):
    worker, created = runtime
    resolved, dispatched = [], []

    async def resolve(owner_id, **kwargs):
        resolved.append(owner_id)
        return config(owner_id)

    async def actor(job):
        return SimpleNamespace(owner_id="alice")

    async def dispatch(self, job, actor):
        dispatched.append(self)
        assert self.engine.generator.llm.llm.config.model == "model-alice"
        assert providers.MeteredChat(self.engine.generator.llm.llm,
                                    config_source="user", api_key="secret-alice").bind_tools([]).config_source == "user"

    worker.runtime_resolver = resolve
    monkeypatch.setattr(rag_owner, "_actor", actor)
    monkeypatch.setattr(rag_owner.OwnerWorker, "_dispatch", dispatch)
    await worker._execute_managed({"mode": "production", "kind": kind})
    assert resolved == ["alice"]
    assert len(dispatched) == 1 and dispatched[0] is not worker
    assert all(model.closed for model in created)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,kind", [("evaluation", "eval_sample"),
                                      ("production", "ingest"), ("production", "delete"),
                                      ("production", "learning_project"), ("production", "images")])
async def test_non_chat_and_evaluation_keep_system_runtime(runtime, mode, kind):
    worker, created = runtime

    async def forbidden(*args, **kwargs):
        pytest.fail("Internal evaluation/retrieval must not resolve a user chat model")

    worker.runtime_resolver = forbidden
    async with user_dispatch.isolated_dispatch(worker, {"mode": mode, "kind": kind},
                                               SimpleNamespace(owner_id="evaluator")) as view:
        assert view is worker
    assert not created


@pytest.mark.asyncio
async def test_failure_and_cancellation_close_models(runtime):
    worker, created = runtime

    async def resolve(*args, **kwargs):
        return config("alice")

    worker.runtime_resolver = resolve
    for failure in (ValueError("invalid result"), asyncio.CancelledError()):
        with pytest.raises(type(failure)):
            async with user_dispatch.isolated_dispatch(worker, {"mode": "production", "kind": "quiz"},
                                                       SimpleNamespace(owner_id="alice")):
                raise failure
        assert all(model.closed for model in created)


@pytest.mark.asyncio
async def test_partial_runtime_construction_closes_already_created_clients(runtime, monkeypatch):
    worker, created = runtime

    async def resolve(*args, **kwargs):
        return config("alice")

    original = providers.chat_model_from_config

    def fail_second_model(config, **kwargs):
        if created:
            raise ValueError("course adapter cannot initialize")
        return original(config, **kwargs)

    worker.runtime_resolver = resolve
    monkeypatch.setattr(providers, "chat_model_from_config", fail_second_model)
    with pytest.raises(ValueError, match="cannot initialize"):
        async with user_dispatch.isolated_dispatch(worker, {"mode": "production", "kind": "quiz"},
                                                   SimpleNamespace(owner_id="alice")):
            pytest.fail("Partially initialized runtime must not dispatch")
    assert len(created) == 1 and created[0].closed


@pytest.mark.asyncio
async def test_real_engine_mandatory_resolver_and_fake_injection(runtime):
    worker, created = runtime
    assert worker.runtime_resolver is user_dispatch.resolve_task_llm_config
    worker.engine.requires_actor_llm = True
    worker.runtime_resolver = None
    with pytest.raises(RuntimeError, match="requires an actor LLM resolver"):
        async with user_dispatch.isolated_dispatch(worker, {"mode": "production", "kind": "quiz"},
                                                   SimpleNamespace(owner_id="alice")):
            pytest.fail("Missing production resolver must never fall back")
    fake = rag_owner.OwnerWorker(SimpleNamespace())
    async with user_dispatch.isolated_dispatch(fake, {"mode": "production", "kind": "quiz"},
                                               SimpleNamespace(owner_id="test")) as view:
        assert view is fake
    assert not created
