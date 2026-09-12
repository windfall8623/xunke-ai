import asyncio
import importlib.util
from types import SimpleNamespace

import pytest

from rag_eval.judges.ragas_adapter import RagasAdapter, calibration_report

HAS_RAGAS = importlib.util.find_spec("ragas") is not None
optional = pytest.mark.skipif(
    not HAS_RAGAS,
    reason="install isolated requirements-ragas.lock for real collections API checks",
)

CONFIG = {
    "enabled": True,
    "model": "local-fake",
    "ragas_version": "0.4.3",
    "prompt_version": "quiz-facts-v1",
    "max_llm_calls": 2,
    "max_cost_cny": 1.0,
    "call_cost_ceiling_cny": 0.1,
    "max_input_tokens": 20000,
    "max_output_tokens": 512,
    "timeout_seconds": 1,
    "total_timeout_seconds": 60,
    "price_table": {
        "effective_date": "2026-09-07",
        "input_cny_per_million": 2,
        "output_cny_per_million": 4,
    },
    "calibrated": False,
}


class FakeProvider:
    def __init__(self, *, timeout=False, empty=False):
        self.timeout, self.empty = timeout, empty
        self.chat = SimpleNamespace(completions=self)

    async def parse(self, **kwargs):
        if self.timeout:
            await asyncio.sleep(0.05)
        model = kwargs["response_format"]
        if model.__name__ == "StatementGeneratorOutput":
            payload = {
                "statements": []
                if self.empty
                else ["Supported statement.", "Unsupported statement."]
            }
        else:
            payload = {
                "statements": [
                    {
                        "statement": "Supported statement.",
                        "reason": "Present in fixture context",
                        "verdict": 1,
                    },
                    {
                        "statement": "Unsupported statement.",
                        "reason": "Contradicts fixture context",
                        "verdict": 0,
                    },
                ]
            }
        parsed = model(**payload)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed))],
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5),
            model="local-fake-v1",
            id="fake-response",
        )


def one_question(artifact):
    artifact["questions"] = artifact["questions"][:1]
    return artifact


@optional
def test_real_ragas_collections_api_preserves_metric_and_all_call_costs(
    quiz_case, quiz_artifact
):
    events = []
    adapter = RagasAdapter(
        CONFIG, client=FakeProvider(), journal=lambda call: events.append(dict(call))
    )
    result = asyncio.run(adapter.score(quiz_case, one_question(quiz_artifact)))
    assert result["metrics"]["ragas_faithfulness"]["value"] == 0.5
    assert len(result["calls"]) == 2
    assert sum(call["cost_cny"] for call in result["calls"]) == pytest.approx(0.000088)
    assert [event["status"] for event in events] == [
        "reserved",
        "completed",
        "reserved",
        "completed",
    ]
    assert result["metadata"]["api"] == "ragas.metrics.collections.Faithfulness.ascore"
    assert result["metadata"]["calibrated"] is False


@optional
def test_judge_timeout_remains_unknown_and_retains_reserved_cost(
    quiz_case, quiz_artifact
):
    adapter = RagasAdapter(
        {**CONFIG, "timeout_seconds": 0.01},
        client=FakeProvider(timeout=True),
        journal=lambda call: None,
    )
    result = asyncio.run(adapter.score(quiz_case, one_question(quiz_artifact)))
    assert result["metrics"]["ragas_faithfulness"]["status"] == "error"
    assert result["metrics"]["ragas_faithfulness"]["reason"] == "judge_timeout"
    assert len(result["calls"]) == 1
    assert result["calls"][0]["reserved_cost_cny"] == 0.1
    assert result["calls"][0]["cost_status"] == "unknown"


@optional
def test_judge_call_budget_includes_both_statement_and_nli_requests(
    quiz_case, quiz_artifact
):
    adapter = RagasAdapter(
        {**CONFIG, "max_llm_calls": 1}, client=FakeProvider(), journal=lambda call: None
    )
    result = asyncio.run(adapter.score(quiz_case, one_question(quiz_artifact)))
    assert len(result["calls"]) == 1
    assert result["metrics"]["ragas_faithfulness"]["reason"] == "judge_budget_exceeded"


@optional
def test_ragas_nan_empty_claims_becomes_na_not_json_nan(quiz_case, quiz_artifact):
    adapter = RagasAdapter(
        CONFIG, client=FakeProvider(empty=True), journal=lambda call: None
    )
    result = asyncio.run(adapter.score(quiz_case, one_question(quiz_artifact)))
    assert result["metrics"]["ragas_faithfulness"]["status"] == "na"
    assert result["metrics"]["ragas_faithfulness"]["value"] is None


def test_external_judge_requires_durable_call_journal(quiz_case, quiz_artifact):
    with pytest.raises(ValueError, match="journal"):
        RagasAdapter(CONFIG)


def test_judge_rejects_nonfinite_prices():
    with pytest.raises(ValueError, match="price"):
        RagasAdapter(
            {
                **CONFIG,
                "price_table": {
                    **CONFIG["price_table"],
                    "input_cny_per_million": float("nan"),
                },
            },
            journal=lambda call: None,
        )


@optional
def test_real_ragas_accepts_native_quiz_shape(quiz_case, quiz_artifact):
    native = one_question(quiz_artifact)
    native["schema_version"] = "quiz-artifact.v1"
    native["evidence_pack"] = {
        "evidence": native.pop("evidence"),
        "provided_evidence_ids": native.pop("context_evidence_ids"),
    }
    question = native["questions"][0]
    question["id"] = question.pop("question_id")
    question["type"] = "single"
    for option in question["options"]:
        option["key"] = option.pop("id")
    result = asyncio.run(
        RagasAdapter(CONFIG, client=FakeProvider(), journal=lambda call: None).score(
            quiz_case, native
        )
    )
    assert result["metrics"]["ragas_faithfulness"]["value"] == 0.5
    assert len(result["calls"]) == 2


def test_calibration_reports_false_accepts_and_never_invents_human_labels():
    records = [
        {
            "question_id": "a",
            "human": True,
            "judge": True,
            "reviewer_id": "reviewer-a",
            "split": "judge_calibration",
        },
        {
            "question_id": "b",
            "human": False,
            "judge": True,
            "reviewer_id": "reviewer-b",
            "split": "judge_calibration",
        },
        {
            "question_id": "c",
            "human": False,
            "judge": False,
            "reviewer_id": "reviewer-a",
            "split": "judge_calibration",
        },
        {
            "question_id": "d",
            "human": None,
            "judge": True,
            "split": "judge_calibration",
        },
    ]
    report = calibration_report(records)
    assert report["confusion_matrix"] == {
        "true_positive": 1,
        "false_positive": 1,
        "true_negative": 1,
        "false_negative": 0,
    }
    assert report["false_accept_rate"]["value"] == 0.5
    assert report["pending_count"] == 1
    assert report["eligible_for_calibration_review"] is False


@optional
def test_uninjected_judge_refuses_missing_endpoint_and_prompt_pin_before_model_calls(
    quiz_case, quiz_artifact
):
    events = []
    result = asyncio.run(
        RagasAdapter(CONFIG, journal=events.append).score(
            quiz_case, one_question(quiz_artifact)
        )
    )
    assert result["metrics"]["ragas_faithfulness"]["reason"] == "judge_profile_invalid"
    assert events == []


@optional
def test_ragas_runtime_inspection_matches_the_prompt_actually_used(
    quiz_case, quiz_artifact
):
    from rag_eval.judges.ragas_adapter import ragas_runtime_info

    inspected = ragas_runtime_info()
    adapter = RagasAdapter(CONFIG, client=FakeProvider(), journal=lambda call: None)
    result = asyncio.run(adapter.score(quiz_case, one_question(quiz_artifact)))
    assert inspected["prompt_hash"] == result["metadata"]["prompt_hash"]
    assert inspected["ragas_version"] == "0.4.3"
    assert inspected["model_calls"] == 0


@optional
@pytest.mark.parametrize(
    "usage,expected_cost",
    [
        (
            {
                "prompt_tokens": 100,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": 80},
            },
            0.000076,
        ),
        (
            {
                "prompt_tokens": 100,
                "completion_tokens": 5,
                "prompt_cache_hit_tokens": 80,
                "prompt_cache_miss_tokens": 20,
            },
            0.000076,
        ),
        ({"prompt_tokens": 100}, None),
        ({"prompt_tokens": 100, "completion_tokens": True}, None),
        (
            {
                "prompt_tokens": 100,
                "completion_tokens": 5,
                "prompt_tokens_details": {"cached_tokens": None},
            },
            None,
        ),
    ],
)
def test_compatible_judge_prices_cache_reads_and_preserves_unknown_raw_usage(
    quiz_case, quiz_artifact, usage, expected_cost
):
    class Provider(FakeProvider):
        async def parse(self, **kwargs):
            result = await super().parse(**kwargs)
            result.usage = SimpleNamespace(**usage)
            return result

    config = {
        **CONFIG,
        "price_table": {
            **CONFIG["price_table"],
            "cache_read_cny_per_million": 0.2,
            "cache_write_cny_per_million": 0.3,
        },
    }
    adapter = RagasAdapter(config, client=Provider(), journal=lambda call: None)
    result = asyncio.run(adapter.score(quiz_case, one_question(quiz_artifact)))
    assert result["metrics"]["ragas_faithfulness"]["value"] == 0.5
    for call in result["calls"]:
        if expected_cost is None:
            assert call["cost_cny"] is None
            assert call["cost_status"] == "unknown"
        else:
            assert call["input_tokens"] == 100
            assert call["input_token_details"] == {"cache_read": 80}
            assert call["cost_cny"] == pytest.approx(expected_cost)
