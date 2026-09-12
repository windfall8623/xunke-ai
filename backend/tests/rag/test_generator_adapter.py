import json

import pytest


def test_generator_rejects_sdk_retries_that_escape_the_pipeline_budget():
    from app.rag.providers.generator import LangChainQuizGenerator

    class RetryModel:
        max_retries = 2

    with pytest.raises(ValueError):
        LangChainQuizGenerator(RetryModel())


@pytest.mark.asyncio
async def test_generator_prompt_uses_only_preassigned_evidence_and_provider_usage():
    from types import SimpleNamespace

    from app.rag.context import assemble_evidence
    from app.rag.coverage import bind_coverage, plan_coverage
    from app.rag.providers.generator import LangChainQuizGenerator
    from tests.rag.test_artifact_pipeline import (
        context_and_scope,
        quiz_for,
        strict_spec,
    )

    evidence, _, _, scope = context_and_scope()
    spec = strict_spec()
    plan = bind_coverage(plan_coverage(spec, scope), [evidence])
    pack = assemble_evidence(
        [evidence], scope, "strict_docs", 6000, "run1", coverage=plan
    )
    messages_seen = []

    class Model:
        max_retries = 0
        model_name = "explicit-fixture"

        async def ainvoke(self, messages):
            messages_seen.extend(messages)
            return SimpleNamespace(
                content=json.dumps(quiz_for(spec, pack, plan), ensure_ascii=False),
                usage_metadata={"input_tokens": 101, "output_tokens": 57},
            )

    result = await LangChainQuizGenerator(Model()).generate(spec, pack, plan, 1)
    assert result.usage.output_tokens == 57
    assert result.payload["questions"][0]["citation_refs"] == ["ev_1"]
    user = json.loads(messages_seen[1].content)
    assert user["evidence"] == [
        {
            "evidence_id": "ev_1",
            "source_type": "document",
            "excerpt": "光合作用需要光。",
        }
    ]
    assert "file_path" not in messages_seen[1].content


@pytest.mark.asyncio
async def test_semantic_checker_rejects_false_without_explicit_counterevidence():
    from types import SimpleNamespace

    from app.rag.context import assemble_evidence
    from app.rag.contracts import QuizPayload
    from app.rag.coverage import bind_coverage, plan_coverage
    from app.rag.providers.generator import LangChainQuizGenerator
    from tests.rag.test_artifact_pipeline import (
        context_and_scope,
        quiz_for,
        strict_spec,
    )

    evidence, _, _, scope = context_and_scope()
    spec = strict_spec()
    plan = bind_coverage(plan_coverage(spec, scope), [evidence])
    pack = assemble_evidence(
        [evidence], scope, "strict_docs", 6000, "run1", coverage=plan
    )
    payload = quiz_for(spec, pack, plan)
    payload["questions"][0].update(
        type="judge",
        answer=["B"],
        options=[{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
    )

    class Model:
        max_retries = 0

        async def ainvoke(self, messages):
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "passed": True,
                        "checks": [
                            {
                                "question_id": "q" + str(i),
                                "source_supported": True,
                                "answer_valid": True,
                                "explanation_valid": True,
                                "not_duplicate": True,
                                "false_has_counterevidence": False,
                            }
                            for i in range(1, 4)
                        ],
                        "errors": [],
                    }
                ),
                usage_metadata={},
            )

    result = await LangChainQuizGenerator(Model()).validate_semantics(
        QuizPayload.model_validate(payload), pack, spec
    )
    assert not result.passed
    assert result.semantic_status == "failed"
    assert any("counterevidence" in error for error in result.errors)


@pytest.mark.asyncio
async def test_model_only_false_question_does_not_claim_nonexistent_source_counterevidence():
    from types import SimpleNamespace

    from app.rag.context import assemble_evidence
    from app.rag.contracts import QuizPayload, QuizSpec, ResolvedScope
    from app.rag.coverage import plan_coverage
    from app.rag.providers.generator import LangChainQuizGenerator
    from tests.rag.test_artifact_pipeline import quiz_for

    spec = QuizSpec(user_input="光合作用", question_count=3)
    scope = ResolvedScope(owner_id=7, namespace="production")
    plan = plan_coverage(spec, scope)
    pack = assemble_evidence([], scope, "topic", 6000, "run1", coverage=plan)
    payload = quiz_for(spec, pack, plan)
    payload["questions"][0].update(
        type="judge",
        stem="光合作用可以在完全无光时进行。",
        answer=["B"],
        options=[{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}],
    )

    class Model:
        max_retries = 0

        async def ainvoke(self, messages):
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "passed": True,
                        "checks": [
                            {
                                "question_id": "q" + str(i),
                                "source_supported": False,
                                "answer_valid": True,
                                "explanation_valid": True,
                                "not_duplicate": True,
                                "false_has_counterevidence": False,
                            }
                            for i in range(1, 4)
                        ],
                        "errors": [],
                    }
                ),
                usage_metadata={},
            )

    result = await LangChainQuizGenerator(Model()).validate_semantics(
        QuizPayload.model_validate(payload), pack, spec
    )
    assert result.passed
    assert result.semantic_details["human_ground_truth"] is False
