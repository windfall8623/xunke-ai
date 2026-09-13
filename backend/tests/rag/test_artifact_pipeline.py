"""Pure LangGraph core: strict refusal, bounded retries and valid provided citations."""

import pytest

from app.rag.contracts import (
    ActorContext,
    DocumentEvidence,
    ExecutionContext,
    PipelineConfig,
    ResolvedScope,
    RetrievalResult,
    SourceManifest,
    ValidationResult,
)
from tests.rag.test_contracts import document_payload


def context_and_scope():
    e = DocumentEvidence.model_validate(document_payload())
    scope = ResolvedScope(
        owner_id=7,
        namespace="evaluation:7",
        documents=[
            SourceManifest(
                owner_id=7,
                namespace="evaluation:7",
                doc_id="doc_1",
                document_version_id="v1",
                source_sha256=e.locator.source_sha256,
                canonical_text_hash=e.locator.canonical_text_hash,
                parse_artifact_id="p1",
                index_build_id="b1",
                attempt_id="a1",
                authorization_revision=1,
            )
        ],
    )
    e = e.model_copy(update={"namespace": "evaluation:7"})
    return (
        e,
        ActorContext(owner_id=7, roles=["evaluator"]),
        ExecutionContext(
            mode="evaluation", run_id="run1", storage_namespace="evaluation:7"
        ),
        scope,
    )


def strict_spec():
    from app.rag.scope import normalize_spec

    return normalize_spec(
        {"user_input": "光合作用", "doc_id": "doc_1", "question_count": 3}
    )


def quiz_for(spec, pack, coverage):
    target = coverage.targets[0].target_id
    citation = pack.provided_evidence_ids[0] if pack.provided_evidence_ids else None
    return {
        "title": "学习练习",
        "summary": "练习",
        "questions": [
            {
                "id": "q" + str(i),
                "type": "single",
                "stem": stem,
                "options": [{"key": "A", "text": "光"}, {"key": "B", "text": "无光"}],
                "answer": ["A"],
                "explanation": "光合作用需要光。",
                "knowledge_point": "光合作用",
                "difficulty": "easy",
                "citation_refs": [citation] if citation else [],
                "coverage_target_id": target,
                "support_quotes": ["光合作用需要光。"] if citation else [],
            }
            for i, stem in enumerate(
                [
                    "光合作用需要什么条件？",
                    "缺少哪种条件会影响光合作用？",
                    "下列哪项满足光合作用的条件？",
                ],
                1,
            )
        ],
    }


@pytest.mark.asyncio
async def test_strict_scope_never_calls_web_or_generator_without_evidence():
    from app.rag.errors import InsufficientEvidence
    from app.rag.pipeline import PipelinePorts, generate_quiz_artifact

    _, actor, context, scope = context_and_scope()

    async def empty(*args, **kwargs):
        return RetrievalResult(status="empty")

    async def forbidden(*args, **kwargs):
        raise AssertionError(
            "Strict refusal must precede external generation/web/learning effects"
        )

    async def authorize(scope):
        return scope

    ports = PipelinePorts(
        retrieve=empty, generate=forbidden, reauthorize=authorize, web_search=forbidden
    )
    with pytest.raises(InsufficientEvidence):
        await generate_quiz_artifact(
            strict_spec(), actor, context, ports, resolved_scope=scope
        )


@pytest.mark.asyncio
async def test_retrieval_failure_has_distinct_error_and_does_not_generate():
    from app.rag.errors import RetrievalUnavailable
    from app.rag.pipeline import PipelinePorts, generate_quiz_artifact

    _, actor, context, scope = context_and_scope()

    async def unavailable(*args, **kwargs):
        raise OSError("database unavailable")

    async def forbidden(*args, **kwargs):
        raise AssertionError("Must not generate after retrieval infrastructure failure")

    async def authorize(scope):
        return True

    with pytest.raises(RetrievalUnavailable):
        await generate_quiz_artifact(
            strict_spec(),
            actor,
            context,
            PipelinePorts(
                retrieve=unavailable, generate=forbidden, reauthorize=authorize
            ),
            resolved_scope=scope,
        )


@pytest.mark.asyncio
async def test_valid_artifact_preserves_evidence_and_requires_model_semantic_check():
    from app.rag.pipeline import PipelinePorts, generate_quiz_artifact

    e, actor, context, scope = context_and_scope()
    dispatched = []
    summaries = []

    async def retrieve(*args, **kwargs):
        return RetrievalResult(evidence=[e], candidates=[e])

    async def generate(spec, pack, coverage, attempt, feedback=None):
        dispatched.extend(pack.provided_evidence_ids)
        return quiz_for(spec, pack, coverage)

    async def semantic(payload, pack, spec):
        return ValidationResult(
            passed=True,
            semantic_status="passed",
            semantic_details={"validator": "explicit-test-fixture"},
        )

    async def authorize(scope):
        return scope

    artifact = await generate_quiz_artifact(
        strict_spec(),
        actor,
        context,
        PipelinePorts(
            retrieve=retrieve,
            generate=generate,
            reauthorize=authorize,
            semantic_validator=semantic,
            record_summary=summaries.append,
        ),
        resolved_scope=scope,
    )
    assert artifact.source_status == "grounded"
    assert artifact.validation.semantic_status == "passed"
    assert artifact.usage.llm_calls == 2
    assert len(artifact.questions) == 3
    assert all(set(q.citation_refs) <= set(dispatched) for q in artifact.questions)
    assert artifact.mode == "evaluation"
    assert artifact.evidence_pack.evidence[0].excerpt == "光合作用需要光。"
    assert [stage["stage"] for stage in artifact.trace] == [
        "plan",
        "retrieve",
        "assemble",
        "generate",
        "validate",
    ]
    assert all("光合作用需要光。" not in str(stage) for stage in artifact.trace)
    assert len(summaries) == 1
    assert summaries[0].status == "completed"
    assert summaries[0].usage == artifact.usage
    assert [stage.stage for stage in summaries[0].stages] == [
        "prepare", "retrieve", "assemble", "generate", "validate", "finish"
    ]


@pytest.mark.asyncio
async def test_unknown_citation_is_retried_twice_then_rejected_without_partial_quiz():
    from app.rag.errors import GenerationValidationFailed
    from app.rag.pipeline import PipelinePorts, generate_quiz_artifact

    e, actor, context, scope = context_and_scope()
    attempts = []

    async def retrieve(*args, **kwargs):
        return RetrievalResult(evidence=[e])

    async def generate(spec, pack, coverage, attempt, feedback=None):
        attempts.append(attempt)
        quiz = quiz_for(spec, pack, coverage)
        quiz["questions"][0]["citation_refs"] = ["hallucinated_id"]
        return quiz

    async def authorize(scope):
        return True

    with pytest.raises(GenerationValidationFailed):
        await generate_quiz_artifact(
            strict_spec(),
            actor,
            context,
            PipelinePorts(retrieve=retrieve, generate=generate, reauthorize=authorize),
            resolved_scope=scope,
        )
    assert attempts == [1, 2]


@pytest.mark.asyncio
async def test_revocation_during_generation_prevents_artifact_return():
    from app.rag.errors import ScopeRevoked
    from app.rag.pipeline import PipelinePorts, generate_quiz_artifact

    e, actor, context, scope = context_and_scope()
    revoked = False

    async def retrieve(*args, **kwargs):
        return RetrievalResult(evidence=[e])

    async def generate(spec, pack, coverage, attempt, feedback=None):
        nonlocal revoked
        revoked = True
        return quiz_for(spec, pack, coverage)

    async def authorize(scope):
        if revoked:
            raise ScopeRevoked("Source removed")

    with pytest.raises(ScopeRevoked):
        await generate_quiz_artifact(
            strict_spec(),
            actor,
            context,
            PipelinePorts(retrieve=retrieve, generate=generate, reauthorize=authorize),
            resolved_scope=scope,
            config=PipelineConfig(require_semantic_validation=False),
        )


@pytest.mark.asyncio
async def test_topic_without_search_is_explicit_model_only():
    from app.rag.pipeline import PipelinePorts, generate_quiz_artifact
    from app.rag.scope import normalize_spec

    _, actor, context, _ = context_and_scope()

    async def forbidden(*args, **kwargs):
        raise AssertionError("Topic mode must not search a private library")

    async def generate(spec, pack, coverage, attempt, feedback=None):
        return quiz_for(spec, pack, coverage)

    async def authorize(scope):
        return None

    artifact = await generate_quiz_artifact(
        normalize_spec({"user_input": "光合作用", "question_count": 3}),
        actor,
        context,
        PipelinePorts(retrieve=forbidden, generate=generate, reauthorize=authorize),
        config=PipelineConfig(require_semantic_validation=False),
    )
    assert artifact.source_status == "model_only"
    assert artifact.evidence_pack.evidence == []
    assert all(q.citation_refs == [] for q in artifact.questions)
    assert artifact.validation.semantic_status == "not_evaluated"


@pytest.mark.asyncio
async def test_evaluation_namespace_prefix_does_not_grant_evaluation_isolation():
    from app.rag.errors import ScopeRevoked
    from app.rag.pipeline import PipelinePorts, generate_quiz_artifact
    from app.rag.scope import normalize_spec

    _, actor, context, _ = context_and_scope()
    context = context.model_copy(update={"storage_namespace": "evaluation-production"})

    async def forbidden(*args, **kwargs):
        raise AssertionError("Malformed evaluation namespace reached a provider")

    with pytest.raises(ScopeRevoked):
        await generate_quiz_artifact(
            normalize_spec({"user_input": "光合作用", "question_count": 3}),
            actor,
            context,
            PipelinePorts(
                retrieve=forbidden, generate=forbidden, reauthorize=forbidden
            ),
        )
