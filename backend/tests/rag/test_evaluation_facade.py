import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["learner", "evaluator"])
@pytest.mark.parametrize(
    "case_type",
    ["retrieval", "quiz", "qa", "policy", "practice_generation", "answer_grading"],
)
async def test_nonadmin_evaluation_denied_before_dispatch(role, case_type):
    from unittest.mock import Mock

    from app.rag.errors import ScopeRevoked
    from app.rag.evaluation import run_eval_sample
    from tests.rag.test_artifact_pipeline import context_and_scope

    _, actor, context, scope = context_and_scope()
    actor = actor.model_copy(update={"roles": [role]})
    engine = Mock()
    with pytest.raises(ScopeRevoked):
        await run_eval_sample({"case_type": case_type}, actor, context, engine, scope)
    assert engine.mock_calls == []


@pytest.mark.asyncio
async def test_retrieval_evaluation_never_calls_quiz_generator():
    from app.rag.contracts import RetrievalArtifact, RetrievalResult
    from app.rag.evaluation import run_eval_sample
    from tests.rag.test_artifact_pipeline import context_and_scope

    e, actor, context, scope = context_and_scope()

    class Engine:
        async def reauthorize(self, scope):
            return True

        async def retrieve(self, query, scope, config, *, budget):
            return RetrievalResult(evidence=[e], candidates=[e])

        async def generate(self, *args, **kwargs):
            raise AssertionError("A retrieval case must not generate a quiz")

    result = await run_eval_sample(
        {
            "case_type": "retrieval",
            "sample_id": "r1",
            "query": "光合作用",
            "scope": {"doc_ids": ["doc_1"]},
        },
        actor,
        context,
        Engine(),
        scope,
    )
    assert isinstance(result, RetrievalArtifact)
    assert result.evidence[0].evidence_id == "ev_1"
    assert result.usage.llm_calls == 0
    assert result.trace["provided_evidence_ids"] == ["ev_1"]


@pytest.mark.asyncio
async def test_eval_case_refuses_a_different_source_parse_without_silent_gold_relabel():
    from app.rag.errors import SourceUnavailable
    from app.rag.evaluation import run_eval_sample
    from tests.rag.test_artifact_pipeline import context_and_scope

    _, actor, context, scope = context_and_scope()
    with pytest.raises(SourceUnavailable):
        await run_eval_sample(
            {
                "case_type": "retrieval",
                "sample_id": "r1",
                "query": "光合作用",
                "source_refs": [
                    {"doc_id": "doc_1", "parse_artifact_id": "another_parse"}
                ],
            },
            actor,
            context,
            None,
            scope,
        )


@pytest.mark.asyncio
async def test_eval_case_cannot_widen_a_chapter_restricted_gold_source():
    from app.rag.errors import ScopeRevoked
    from app.rag.evaluation import run_eval_sample
    from tests.rag.test_artifact_pipeline import context_and_scope

    _, actor, context, scope = context_and_scope()
    with pytest.raises(ScopeRevoked):
        await run_eval_sample(
            {
                "case_type": "retrieval",
                "query": "光合作用",
                "source_refs": [{"doc_id": "doc_1", "section_ids": ["p1:chapter-1"]}],
            },
            actor,
            context,
            None,
            scope,
        )


@pytest.mark.asyncio
async def test_retrieval_evaluation_deadline_cancels_hung_provider_and_preserves_usage():
    import asyncio

    from app.rag.contracts import BudgetLimits, RetrievalResult
    from app.rag.errors import BudgetExceeded
    from app.rag.evaluation import run_eval_sample
    from tests.rag.test_artifact_pipeline import context_and_scope

    _, actor, context, scope = context_and_scope()
    context = context.model_copy(update={"budget": BudgetLimits(deadline_seconds=0.03)})
    cancelled = asyncio.Event()

    class Engine:
        async def retrieve(self, query, scope, config, *, budget):
            budget.reserve("embedding", input_tokens=3)
            try:
                await asyncio.sleep(0.5)
                return RetrievalResult()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    with pytest.raises(BudgetExceeded) as caught:
        await run_eval_sample(
            {
                "case_type": "retrieval",
                "sample_id": "timeout-case",
                "query": "光合作用",
            },
            actor,
            context,
            Engine(),
            scope,
        )
    assert cancelled.is_set()
    assert caught.value.details["usage"]["embedding_calls"] == 1
    assert caught.value.details["usage"]["stage_ms"]["retrieval"] > 0


@pytest.mark.asyncio
async def test_policy_harness_rejects_production_target_before_touching_engine():
    from app.rag.errors import ScopeRevoked
    from app.rag.evaluation import run_eval_sample
    from tests.rag.test_artifact_pipeline import context_and_scope

    _, actor, context, scope = context_and_scope()
    with pytest.raises(ScopeRevoked):
        await run_eval_sample(
            {
                "case_type": "policy",
                "harness": {
                    "synthetic_only": True,
                    "actors": [{"actor_id": "alice", "synthetic": True}],
                    "resources": [
                        {
                            "resource_id": "production-doc",
                            "source_doc_id": "doc_1",
                            "synthetic": True,
                            "namespace": "production",
                        }
                    ],
                    "steps": [{"action": "source_delete", "target": "production-doc"}],
                },
            },
            actor,
            context,
            None,
            scope,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action",
    [
        "cross_owner_read",
        "source_delete",
        "source_revoke",
        "expired_authorization",
        "stale_publish",
        "production_side_effect",
    ],
)
async def test_policy_harness_exercises_guard_on_disposable_synthetic_copy(action):
    from app.rag.contracts import PolicyArtifact
    from app.rag.evaluation import run_eval_sample
    from tests.rag.test_artifact_pipeline import context_and_scope

    _, actor, context, scope = context_and_scope()
    sample = {
        "case_type": "policy",
        "harness": {
            "synthetic_only": True,
            "actors": [
                {"actor_id": "alice", "synthetic": True},
                {"actor_id": "bob", "synthetic": True},
            ],
            "resources": [
                {
                    "resource_id": "synthetic-copy",
                    "source_doc_id": "doc_1",
                    "synthetic": True,
                    "namespace": "evaluation",
                }
            ],
            "steps": [{"action": action, "target": "synthetic-copy"}],
        },
    }
    result = await run_eval_sample(sample, actor, context, None, scope)
    assert isinstance(result, PolicyArtifact)
    assert result.observations["actual_status"] == "denied"
    assert result.observations["production_side_effect_count"] == 0
    assert result.observations["unauthorized_source_count"] == 0
    assert result.observations["stale_publish_count"] == 0
    assert result.observations["executed_step_count"] == 1
    assert result.observations["harness_kind"] == "in_memory_scope_guards"
