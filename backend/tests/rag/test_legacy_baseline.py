"""B0 is executable only inside an authorized isolated evaluation scope."""

import hashlib
import io
import json
import tarfile
from types import SimpleNamespace

import pytest


def archive(tmp_path):
    path = tmp_path / "legacy-source.tar.gz"
    sources = {
        "backend/app/prompts/rag_prompt.py": 'RAG_AGENT_SYSTEM_PROMPT = "Frozen original summary policy"',
        "backend/app/prompts/quiz_prompt.py": 'QUIZ_SYSTEM_PROMPT = "Frozen quiz policy"\nQUIZ_HUMAN_PROMPT = "{question_count}|{difficulty}|{user_input}|{search_context_section}"\nSEARCH_CONTEXT_TEMPLATE = "Reference: {search_context}"',
        "backend/app/services/rag_service.py": "MAX_CONTEXT_LENGTH = 3000\nAGENT_TIMEOUT_SECONDS = 60",
    }
    with tarfile.open(path, "w:gz") as bundle:
        for name, text in sources.items():
            blob = text.encode()
            member = tarfile.TarInfo(name)
            member.size = len(blob)
            bundle.addfile(member, io.BytesIO(blob))
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_legacy_baseline_executes_frozen_summary_truncation_and_quiz_prompt(
    tmp_path,
):
    from app.rag.context import assemble_evidence
    from app.rag.coverage import plan_coverage
    from app.rag.providers.legacy_baseline import LegacyBaselineAdapter
    from tests.rag.test_artifact_pipeline import (
        context_and_scope,
        quiz_for,
        strict_spec,
    )

    _, actor, context, scope = context_and_scope()
    spec = strict_spec()
    payload = quiz_for(
        spec,
        assemble_evidence([], scope, "topic", 6000, "r"),
        plan_coverage(spec, scope),
    )
    for question in payload["questions"]:
        question.pop("coverage_target_id")
    observed = []

    class SummaryAgent:
        async def ainvoke(self, messages, config):
            return {"messages": [SimpleNamespace(content="a" * 4000)]}

    class Model:
        max_retries = 0
        model_name = "explicit-test-fixture"

        async def ainvoke(self, messages):
            observed.extend(messages)
            return SimpleNamespace(
                content=json.dumps(payload),
                usage_metadata={"input_tokens": 40, "output_tokens": 60},
            )

    async def authorize(scope):
        return True

    path, checksum = archive(tmp_path)
    adapter = LegacyBaselineAdapter(
        source_archive=path,
        archive_sha256=checksum,
        llm=Model(),
        retriever=None,
        reauthorize=authorize,
        summary_agent=SummaryAgent(),
    )
    artifact = await adapter.run(spec, actor, context, scope)
    assert observed[0].content == "Frozen quiz policy"
    assert "a" * 3000 in observed[1].content and "a" * 3001 not in observed[1].content
    assert artifact.source_status == "legacy_unverified"
    assert artifact.effective_config["baseline"]["source_archive_sha256"] == checksum


@pytest.mark.asyncio
async def test_legacy_baseline_refuses_production_and_changed_source_archive(tmp_path):
    from app.rag.errors import ScopeRevoked, SourceUnavailable
    from app.rag.providers.legacy_baseline import LegacyBaselineAdapter
    from tests.rag.test_artifact_pipeline import context_and_scope, strict_spec

    _, actor, context, scope = context_and_scope()
    path, checksum = archive(tmp_path)
    with pytest.raises(SourceUnavailable):
        LegacyBaselineAdapter(
            source_archive=path,
            archive_sha256="0" * 64,
            llm=None,
            retriever=None,
            reauthorize=lambda s: True,
        )
    adapter = LegacyBaselineAdapter(
        source_archive=path,
        archive_sha256=checksum,
        llm=None,
        retriever=None,
        reauthorize=lambda s: True,
    )
    with pytest.raises(ScopeRevoked):
        await adapter.run(
            strict_spec(),
            actor,
            context.model_copy(update={"mode": "production"}),
            scope,
        )


@pytest.mark.asyncio
async def test_owner_baseline_binding_executes_tool_summary_then_frozen_quiz_with_one_config_pin(
    tmp_path,
):
    from langchain_core.messages import AIMessage

    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.context import assemble_evidence
    from app.rag.contracts import ActorContext, ExecutionContext
    from app.rag.coverage import plan_coverage
    from app.rag.engine import RagEngine
    from app.rag.evaluation import run_eval_sample
    from app.rag.scope import normalize_spec
    from tests.rag.helpers import FixtureEmbedding, request_for, scope_for
    from tests.rag.test_artifact_pipeline import quiz_for

    archive_path, checksum = archive(tmp_path)
    messages_seen = []

    class ToolModel:
        max_retries = 0
        model_name = "explicit-frozen-fixture"
        calls = 0

        def bind_tools(self, tools):
            assert [tool.name for tool in tools] == ["search_knowledge_base"]
            return self

        async def ainvoke(self, messages):
            self.calls += 1
            messages_seen.append(messages)
            if self.calls == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "search_knowledge_base",
                            "args": {"query": "光合作用"},
                            "id": "c1",
                            "type": "tool_call",
                        }
                    ],
                )
            if self.calls == 2:
                return AIMessage(content="光合作用需要光。")
            return AIMessage(content=json.dumps(payload, ensure_ascii=False))

    async def authorize(scope):
        return scope

    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store:
        engine = RagEngine(store, FixtureEmbedding(), reauthorize=authorize)
        built = await engine.build(
            request_for(tmp_path, namespace="evaluation:7", text="光合作用需要光。")
        )
        scope = scope_for(built)
        spec = normalize_spec(
            {"user_input": "光合作用", "doc_id": "d1", "question_count": 3}
        )
        payload = quiz_for(
            spec,
            assemble_evidence([], scope, "topic", 6000, "r"),
            plan_coverage(spec, scope),
        )
        config = engine.configure_legacy_baseline(
            source_archive=archive_path, archive_sha256=checksum, llm=ToolModel()
        )
        actor = ActorContext(owner_id=7, roles=["admin"])
        context = ExecutionContext(
            mode="evaluation", run_id="b0-run", storage_namespace="evaluation:7"
        )
        result = await run_eval_sample(
            {
                "case_type": "quiz",
                "sample_id": "b0-case",
                "user_input": "光合作用",
                "question_count": 3,
            },
            actor,
            context,
            engine,
            scope,
            config,
        )

    assert result.pipeline_version == "legacy-summary-b0"
    assert result.pipeline_config_hash == config.pipeline_config_hash
    assert config.legacy_source_archive_sha256 == checksum
    assert result.usage.llm_calls == 3
    assert result.usage.embedding_calls == 1
    assert result.source_status == "legacy_unverified"
    assert "Reference: 光合作用需要光。" in messages_seen[-1][-1].content
    assert all(not question.citation_refs for question in result.questions)


@pytest.mark.asyncio
async def test_baseline_rejects_a_run_pinned_to_a_different_source_archive(tmp_path):
    from app.rag.errors import SourceUnavailable
    from app.rag.providers.legacy_baseline import LegacyBaselineAdapter
    from app.rag.registry import get_pipeline_config
    from tests.rag.test_artifact_pipeline import context_and_scope, strict_spec

    _, actor, context, scope = context_and_scope()
    path, checksum = archive(tmp_path)
    adapter = LegacyBaselineAdapter(
        source_archive=path,
        archive_sha256=checksum,
        llm=None,
        retriever=None,
        reauthorize=lambda s: True,
    )
    config = get_pipeline_config(
        "legacy-summary-b0",
        legacy_source_archive_sha256="0" * 64,
        legacy_source_commit="7302ad2",
    )
    with pytest.raises(SourceUnavailable):
        await adapter.run(strict_spec(), actor, context, scope, config=config)
