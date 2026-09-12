"""QA evaluation uses the same facade, with portable same-scope history."""

from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter, ValidationError

from app.models.eval_contracts import EvalSample
from app.rag.contracts import PipelineConfig
from app.rag.errors import InvalidScope, ScopeRevoked
from app.rag.evaluation import run_eval_sample
from tests.rag.test_artifact_pipeline import context_and_scope


def sample(**updates):
    return {
        "schema_version": "1",
        "case_type": "qa",
        "sample_id": "qa-1",
        "split": "dev",
        "question": "What do plants need?",
        "history": [],
        "expected_answer_status": "answered",
        "source_refs": [{"doc_id": "doc_1"}],
        **updates,
    }


def test_qa_is_a_fourth_dataset_discriminator_and_has_portable_history():
    value = TypeAdapter(EvalSample).validate_python(
        sample(
            history=[
                {"question": "What process?", "answer": "Photosynthesis."},
            ]
        )
    )
    assert value.case_type == "qa"
    assert value.history[0].answer == "Photosynthesis."
    assert value.expected_answer_status == "answered"


@pytest.mark.parametrize(
    "updates",
    [
        {"question": "  "},
        {"question": "q" * 2001},
        {"expected_answer_status": "failed"},
        {"expected_answer_status": None},
        {"expected_error_code": "SOURCE_UNAVAILABLE"},
        {"history": [{"question": "q", "answer": " "}]},
        {"history": [{"question": "q", "answer": "a", "scope_fingerprint": "foreign"}]},
        {"history": [{"question": "q", "answer": "a"}] * 7},
        {"history": [{"question": "q", "answer": "a" * 8000}]},
    ],
)
def test_qa_dataset_rejects_invalid_question_status_and_history(updates):
    with pytest.raises(ValidationError):
        TypeAdapter(EvalSample).validate_python(sample(**updates))


def test_technical_failure_expectation_is_separate_from_answer_status():
    value = TypeAdapter(EvalSample).validate_python(
        sample(
            expected_answer_status=None,
            expected_error_code="SOURCE_UNAVAILABLE",
        )
    )
    assert value.expected_answer_status is None
    assert value.expected_error_code == "SOURCE_UNAVAILABLE"


def test_qa_expected_error_without_explicit_null_status_matches_portable_schema():
    from rag_eval.qa import validate_qa_sample

    data = sample(expected_error_code="SOURCE_UNAVAILABLE")
    data.pop("expected_answer_status")
    assert validate_qa_sample(data) == []
    assert TypeAdapter(EvalSample).validate_python(data).expected_answer_status is None


def test_qa_dataset_requires_a_nonempty_source_scope():
    with pytest.raises(ValidationError):
        TypeAdapter(EvalSample).validate_python(sample(source_refs=[]))


@pytest.mark.asyncio
async def test_qa_dispatch_cannot_add_documents_not_in_the_sample_scope():
    _, actor, context, scope = context_and_scope()
    scope = scope.model_copy(
        update={
            "documents": [
                *scope.documents,
                scope.documents[0].model_copy(update={"doc_id": "extra"}),
            ]
        }
    )
    with pytest.raises(ScopeRevoked):
        await run_eval_sample(sample(), actor, context, None, scope)


@pytest.mark.asyncio
async def test_dispatch_binds_history_to_resolved_evaluation_scope():
    from app.qa.contracts import ChatAnswerArtifact
    from app.rag.evaluation_artifacts import EvaluationArtifact

    e, actor, context, scope = context_and_scope()
    calls = []

    class Engine:
        async def answer(
            self, question, history, actual_actor, actual_context, actual_scope, config
        ):
            calls.append(
                (question, history, actual_actor, actual_context, actual_scope)
            )
            return ChatAnswerArtifact(
                run_id=context.run_id,
                answer_status="answered",
                blocks=[
                    {
                        "block_id": "b1",
                        "text": e.excerpt,
                        "citation_refs": [e.evidence_id],
                    }
                ],
                evidence=[e],
                retrieval_query=question,
                scope_fingerprint=scope.fingerprint,
                pipeline_config_hash="a" * 64,
            )

        async def generate(self, *args, **kwargs):
            raise AssertionError("QA evaluation may not call quiz generation")

    result = await run_eval_sample(
        sample(history=[{"question": "Earlier", "answer": "Light"}]),
        actor,
        context,
        Engine(),
        scope,
    )
    assert result.case_type == "qa"
    assert result.effective_config["sample_id"] == "qa-1"
    assert (
        TypeAdapter(EvaluationArtifact).validate_python(result.model_dump()).case_type
        == "qa"
    )
    question, history, actual_actor, actual_context, actual_scope = calls[0]
    assert question == "What do plants need?"
    assert history[0].scope_fingerprint == scope.fingerprint
    assert history[0].answer == "Light"
    assert actual_actor is actor and actual_context is context and actual_scope is scope


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["owner", "namespace", "source", "history", "legacy"]
)
async def test_qa_dispatch_rejects_unsafe_or_unsupported_inputs_before_model(change):
    _, actor, context, scope = context_and_scope()
    data, config = sample(), PipelineConfig()
    expected = ScopeRevoked
    if change == "owner":
        actor = actor.model_copy(update={"owner_id": 99})
    elif change == "namespace":
        scope = scope.model_copy(update={"namespace": "production"})
    elif change == "source":
        data["source_refs"] = [{"doc_id": "foreign"}]
    elif change == "history":
        data["history"] = [
            {"question": "q", "answer": "a", "scope_fingerprint": "foreign"}
        ]
        expected = InvalidScope
    elif change == "legacy":
        config = config.model_copy(update={"pipeline_version": "legacy-summary-b0"})
        expected = InvalidScope
    with pytest.raises(expected):
        await run_eval_sample(data, actor, context, None, scope, config)


def settings_for_cost(**prices):
    data = {
        "llm_input_cny_per_million": 2.0,
        "llm_output_cny_per_million": 8.0,
        "embedding_cny_per_million": 1.0,
        "rerank_call_cny": 0.01,
        **prices,
    }
    return SimpleNamespace(
        model_dump=lambda: data,
        job_max_attempts=2,
        pricing_version="synthetic-test",
        enable_web_search=False,
        tavily_api_key="",
    )


@pytest.mark.parametrize(
    "history,expected_calls", [([], 2), ([{"question": "q", "answer": "a"}], 3)]
)
def test_qa_preview_prices_rewrite_and_mandatory_semantic_validation(
    history, expected_calls
):
    from app.services.evaluation_cost_preview import estimate_cost

    result = estimate_cost(
        [sample(history=history)],
        PipelineConfig(retriever="bm25", require_semantic_validation=False),
        {"metric_version": "evidence-v1"},
        settings_for_cost(),
        repeat_count=2,
    )
    parts = {part["stage"]: part for part in result["components"]}
    assert result["status"] == "estimated"
    assert parts["generation"]["first_attempt_calls"] == expected_calls * 2
    assert parts["generation"]["retry_scenario_calls"] <= 5 * 2
    assert parts["scoring"]["status"] == "not_applicable"
    assert parts["retrieval"]["first_attempt_calls"] == 0


def test_qa_preview_does_not_turn_missing_prices_into_free_calls():
    from app.services.evaluation_cost_preview import estimate_cost

    result = estimate_cost(
        [sample()],
        PipelineConfig(retriever="bm25"),
        {},
        settings_for_cost(llm_output_cny_per_million=None),
        repeat_count=1,
    )
    assert result["status"] == "unknown"
    assert result["first_attempt_cny"] is None


def test_qa_judge_calibration_never_inherits_quiz_calibration():
    from app.services.evaluation_service import judge_calibrated_for_samples

    assert (
        judge_calibrated_for_samples(
            [sample()], {"external_judge": {"calibrated": True}}
        )
        is False
    )
    assert (
        judge_calibrated_for_samples(
            [{"case_type": "quiz"}], {"external_judge": {"calibrated": True}}
        )
        is True
    )
    assert judge_calibrated_for_samples([{"case_type": "retrieval"}], {}) is True
