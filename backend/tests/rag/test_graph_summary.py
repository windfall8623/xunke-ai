"""Bounded summaries observe existing graph decisions without private payloads."""

import asyncio

import pytest
from pydantic import ValidationError

from app.rag.contracts import PipelineConfig, RetrievalResult, Usage, ValidationResult
from app.rag.errors import BudgetExceeded, GenerationValidationFailed, ScopeRevoked
from app.rag.graph_trace import GraphExecutionSummary, GraphSummaryRecorder
from app.rag.pipeline import PipelinePorts, generate_quiz_artifact
from tests.rag.test_artifact_pipeline import context_and_scope, quiz_for, strict_spec


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path, retrievals, attempts, llm_calls",
    [
        ("normal", 1, [1], 2),
        ("extra_retrieval", 2, [1], 2),
        ("repair", 1, [1, 2], 3),
        ("budget_stop", 1, [1], 1),
    ],
)
async def test_existing_paths_preserve_artifacts_and_report_actual_branches(
    path, retrievals, attempts, llm_calls
):
    evidence, actor, context, scope = context_and_scope()
    if path == "budget_stop":
        context = context.model_copy(
            update={"budget": context.budget.model_copy(update={"max_llm_calls": 1})}
        )
    summaries, events, generated_payloads = [], [], []

    async def retrieve(*args, **kwargs):
        events.append("retrieve")
        if path == "extra_retrieval" and events.count("retrieve") == 1:
            return RetrievalResult(status="empty")
        return RetrievalResult(evidence=[evidence], candidates=[evidence])

    async def generate(spec, pack, coverage, attempt, feedback=None):
        events.append(attempt)
        payload = quiz_for(spec, pack, coverage)
        if path == "repair" and attempt == 1:
            payload["questions"][0]["citation_refs"] = ["private-citation-marker"]
        generated_payloads.append(payload)
        return payload

    async def semantic(*args):
        events.append("semantic")
        return ValidationResult(
            passed=True,
            semantic_status="passed",
            semantic_details={"private": "private-provider-body"},
        )

    async def forbidden(*args, **kwargs):
        raise AssertionError("Strict sources must never search the web")

    async def authorize(selected_scope):
        return selected_scope

    config = PipelineConfig()
    task = generate_quiz_artifact(
        strict_spec(),
        actor,
        context,
        PipelinePorts(
            retrieve=retrieve,
            generate=generate,
            reauthorize=authorize,
            web_search=forbidden,
            semantic_validator=semantic,
            record_summary=summaries.append,
        ),
        resolved_scope=scope,
        config=config,
    )
    if path == "budget_stop":
        with pytest.raises(BudgetExceeded) as rejected:
            await task
        assert rejected.value.details["resource"] == "llm"
        assert rejected.value.details["usage"]["llm_calls"] == 1
        assert "semantic" not in events
    else:
        artifact = await task
        assert [question.model_dump() for question in artifact.questions] == (
            generated_payloads[-1]["questions"]
        )
        assert artifact.evidence_pack.evidence == [evidence]
        assert artifact.evidence_pack.provided_evidence_ids == [evidence.evidence_id]
        assert artifact.source_status == "grounded"
        assert artifact.validation.semantic_status == "passed"
        assert artifact.usage.llm_calls == llm_calls
        assert artifact.pipeline_config_hash == config.pipeline_config_hash
        assert [item["stage"] for item in artifact.trace] == (
            ["plan"] + ["retrieve", "assemble"] * retrievals
            + ["generate", "validate"] * len(attempts)
        )

    assert events.count("retrieve") == retrievals
    assert [event for event in events if isinstance(event, int)] == attempts
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.graph == "rag_quiz"
    assert summary.run_id == context.run_id
    expected_stages = ["prepare"] + ["retrieve", "assemble"] * retrievals
    expected_stages += ["generate", "validate"] * len(attempts)
    if path != "budget_stop":
        expected_stages += ["finish"]
    assert [stage.stage for stage in summary.stages] == expected_stages
    assert [stage.seq for stage in summary.stages] == list(
        range(1, len(expected_stages) + 1)
    )
    assert summary.usage.llm_calls == llm_calls
    assert sum(stage.llm_calls_delta for stage in summary.stages) == llm_calls
    assert [
        stage.retrieval_round for stage in summary.stages if stage.stage == "retrieve"
    ] == list(range(1, retrievals + 1))
    assert [
        stage.generation_attempt for stage in summary.stages if stage.stage == "generate"
    ] == attempts
    assert [stage.branch for stage in summary.stages].count("retry_retrieval") == (
        path == "extra_retrieval"
    )
    assert [stage.branch for stage in summary.stages].count("retry_generation") == (
        path == "repair"
    )
    assert all(stage.duration_ms >= 0 for stage in summary.stages)
    assert summary.status == ("failed" if path == "budget_stop" else "completed")
    assert summary.terminal_reason == (
        "budget_exceeded" if path == "budget_stop" else "completed"
    )
    if path == "budget_stop":
        assert summary.stages[-1].status == "failed"
        assert summary.stages[-1].error_code == "budget_exceeded"
        assert summary.stages[-1].branch == "stop"
    serialized = summary.model_dump_json()
    for private in [
        strict_spec().user_input, evidence.excerpt,
        "private-provider-body", "private-citation-marker",
    ]:
        assert private not in serialized


@pytest.mark.asyncio
async def test_conditional_validation_failure_preserves_error_and_records_stop():
    evidence, actor, context, scope = context_and_scope()
    summaries = []

    async def retrieve(*args, **kwargs):
        return RetrievalResult(evidence=[evidence])

    async def generate(spec, pack, coverage, attempt, feedback=None):
        payload = quiz_for(spec, pack, coverage)
        payload["questions"][0]["citation_refs"] = ["private-unknown-citation"]
        return payload

    with pytest.raises(GenerationValidationFailed) as rejected:
        await generate_quiz_artifact(
            strict_spec(), actor, context,
            PipelinePorts(
                retrieve=retrieve, generate=generate, reauthorize=lambda scope: True,
                record_summary=summaries.append,
            ),
            resolved_scope=scope,
        )
    assert rejected.value.details["validation_errors"]
    assert rejected.value.details["usage"]["llm_calls"] == 2
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary.terminal_reason == "generation_validation_failed"
    assert summary.stages[-1].stage == "validate"
    assert summary.stages[-1].status == "failed"
    assert summary.stages[-1].branch == "stop"
    assert summary.stages[-1].generation_attempt == 2
    assert "private-unknown-citation" not in summary.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancelled", "preflight"])
async def test_cancelled_and_preflight_failures_do_not_fabricate_stages(failure):
    evidence, actor, context, scope = context_and_scope()
    summaries = []
    cancelled = asyncio.CancelledError("private-cancellation-body")
    if failure == "preflight":
        context = context.model_copy(update={"storage_namespace": "wrong-namespace"})

    async def retrieve(*args, **kwargs):
        return RetrievalResult(evidence=[evidence])

    async def generate(*args, **kwargs):
        raise cancelled

    with pytest.raises(asyncio.CancelledError if failure == "cancelled" else ScopeRevoked):
        await generate_quiz_artifact(
            strict_spec(), actor, context,
            PipelinePorts(
                retrieve=retrieve, generate=generate, reauthorize=lambda scope: True,
                record_summary=summaries.append,
            ),
            resolved_scope=scope,
        )
    assert len(summaries) == 1
    summary = summaries[0]
    if failure == "preflight":
        assert summary.stages == []
        assert summary.status == "failed"
        assert summary.terminal_reason == "source_unavailable"
        assert summary.usage.llm_calls == 0
    else:
        assert summary.status == summary.terminal_reason == "cancelled"
        assert summary.stages[-1].stage == "generate"
        assert summary.stages[-1].status == "cancelled"
        assert summary.stages[-1].llm_calls_delta == 1
    assert "private-cancellation-body" not in summary.model_dump_json()


@pytest.mark.asyncio
async def test_failing_sink_cannot_change_questions_evidence_or_call_count(caplog):
    evidence, actor, context, scope = context_and_scope()
    seen = []

    def failing_sink(summary):
        seen.append(summary)
        raise ValueError("private-callback-body")

    async def retrieve(*args, **kwargs):
        return RetrievalResult(evidence=[evidence])

    async def generate(spec, pack, coverage, attempt, feedback=None):
        return quiz_for(spec, pack, coverage)

    async def semantic(*args):
        return ValidationResult(passed=True, semantic_status="passed")

    async def run(sink):
        return await generate_quiz_artifact(
            strict_spec(), actor, context,
            PipelinePorts(
                retrieve=retrieve, generate=generate, reauthorize=lambda scope: True,
                semantic_validator=semantic, record_summary=sink,
            ),
            resolved_scope=scope,
        )

    baseline = await run(None)
    observed = await run(failing_sink)
    assert observed.questions == baseline.questions
    assert observed.artifact_id == baseline.artifact_id
    assert observed.evidence_pack.evidence == baseline.evidence_pack.evidence
    assert observed.evidence_pack.provided_evidence_ids == (
        baseline.evidence_pack.provided_evidence_ids
    )
    assert observed.usage.llm_calls == baseline.usage.llm_calls == 2
    assert observed.trace == baseline.trace
    assert len(seen) == 1
    assert "graph_summary_sink_failed" in caplog.text
    assert "private-callback-body" not in caplog.text


def test_recorder_copies_counts_uses_monotonic_time_and_accepts_teaching_revision():
    now = [10.0]
    recorder = GraphSummaryRecorder("course_teaching", "run1", clock=lambda: now[0])
    usage = Usage()
    recorder.begin("teacher", usage)
    usage.llm_calls = 1
    usage.input_tokens = 12
    usage.output_tokens = 7
    now[0] = 11.0
    recorder.end(
        "teacher", usage, status="completed", branch="next", generation_revision=1
    )
    summary = recorder.finish(status="completed", terminal_reason="completed", usage=usage)
    usage.output_tokens = 90
    stage = summary.stages[0]
    assert stage.duration_ms == 1000
    assert stage.llm_calls_delta == 1
    assert stage.input_tokens_delta == 12
    assert stage.output_tokens_delta == 7
    assert stage.generation_revision == 1
    assert summary.usage.output_tokens == 7


def test_recorder_reports_counter_reversal_without_negative_usage(caplog):
    recorder = GraphSummaryRecorder("rag_quiz", "run1", clock=lambda: 1.0)
    recorder.begin("retrieve", Usage(llm_calls=2, input_tokens=10, output_tokens=20))
    recorder.end(
        "retrieve", Usage(llm_calls=1, input_tokens=8, output_tokens=19),
        status="completed", branch="next", retrieval_round=1,
    )
    summary = recorder.finish(
        status="completed", terminal_reason="completed", usage=Usage(llm_calls=1)
    )
    assert summary.stages[0].llm_calls_delta == 0
    assert summary.stages[0].input_tokens_delta == 0
    assert summary.stages[0].output_tokens_delta == 0
    assert "graph_summary_usage_decreased" in caplog.text


@pytest.mark.parametrize("field", ["prompt", "excerpt", "answer", "lease_token"])
def test_summary_contract_rejects_private_fields(field):
    raw = {
        "graph": "rag_quiz", "run_id": "run1", "status": "completed",
        "terminal_reason": "completed", "usage": {}, field: "private-material",
    }
    with pytest.raises(ValidationError):
        GraphExecutionSummary.model_validate(raw)


@pytest.mark.parametrize("field", ["stage", "error_code", "terminal_reason"])
def test_summary_contract_rejects_unregistered_names_and_freeform_errors(field):
    recorder = GraphSummaryRecorder("rag_quiz", "run1", clock=lambda: 1.0)
    recorder.begin("prepare", Usage())
    recorder.end("prepare", Usage(), status="completed", branch="next")
    raw = recorder.finish(
        status="completed", terminal_reason="completed", usage=Usage()
    ).model_dump(mode="json")
    if field == "terminal_reason":
        raw[field] = "private-provider-message"
    else:
        raw["stages"][0][field] = "private-provider-message"
    with pytest.raises(ValidationError):
        GraphExecutionSummary.model_validate(raw)
