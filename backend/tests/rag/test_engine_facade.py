import pytest


@pytest.mark.asyncio
async def test_owner_engine_build_retrieve_and_generate_without_learning_ports(
    tmp_path,
):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import ActorContext, ExecutionContext, ValidationResult
    from app.rag.engine import RagEngine
    from app.rag.scope import normalize_spec
    from tests.rag.helpers import FixtureEmbedding, request_for, scope_for
    from tests.rag.test_artifact_pipeline import quiz_for

    class Generator:
        async def generate(self, spec, pack, coverage, attempt, feedback=None):
            return quiz_for(spec, pack, coverage)

        async def validate_semantics(self, payload, pack, spec):
            return ValidationResult(passed=True, semantic_status="passed")

    async def authorize(scope):
        return scope

    with OwnerIndexStore(tmp_path / "data", process_role="rag_owner") as store:
        engine = RagEngine(store, FixtureEmbedding(), Generator(), authorize)
        built = await engine.build(
            request_for(tmp_path, namespace="evaluation:7", text="光合作用需要光。")
        )
        artifact = await engine.generate(
            normalize_spec(
                {"user_input": "光合作用", "doc_id": "d1", "question_count": 3}
            ),
            ActorContext(owner_id=7, roles=["admin"]),
            ExecutionContext(
                mode="evaluation", run_id="run1", storage_namespace="evaluation:7"
            ),
            scope_for(built),
        )
        assert len(artifact.questions) == 3
        assert artifact.source_status == "grounded"
        assert artifact.evidence_pack.resolved_scope.documents[0].attempt_id == "a1"


def test_registry_unknown_pipeline_or_unbounded_override_is_rejected():
    from pydantic import ValidationError

    from app.rag.registry import get_pipeline_config

    assert get_pipeline_config("llamaindex-dense-v1").retriever == "llamaindex_dense"
    with pytest.raises(ValueError):
        get_pipeline_config("unknown")
    with pytest.raises(ValidationError):
        get_pipeline_config("hybrid-v1", max_generation_attempts=99)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reason", ["different_actor", "revoked_source", "wrong_namespace"]
)
async def test_generation_rejects_invalid_authorization_before_loading_private_catalog(
    reason,
):
    from app.rag.engine import RagEngine
    from app.rag.errors import ScopeRevoked
    from tests.rag.test_artifact_pipeline import context_and_scope, strict_spec

    _, actor, context, scope = context_and_scope()
    if reason == "different_actor":
        actor = actor.model_copy(update={"owner_id": 8})
    if reason == "wrong_namespace":
        context = context.model_copy(update={"storage_namespace": "production"})

    class PrivateStore:
        def read_build(self, manifest):
            raise AssertionError("Private catalog read preceded authorization")

    async def authorize(scope):
        return reason != "revoked_source"

    engine = RagEngine(PrivateStore(), None, object(), authorize)
    with pytest.raises(ScopeRevoked):
        await engine.generate(strict_spec(), actor, context, scope)
