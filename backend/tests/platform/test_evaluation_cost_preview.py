import pytest
from tests.platform.conftest import register_email_account

from app.core.config import Settings
from app.rag.contracts import PipelineConfig


def preview(samples, *, repeat_count=1, scorer=None, **prices):
    from app.services.evaluation_cost_preview import estimate_cost

    settings = Settings(
        _env_file=None,
        enable_web_search=False,
        pricing_version="fixture-price-v1",
        **prices,
    )
    return estimate_cost(
        samples,
        PipelineConfig(retriever="llamaindex_dense"),
        scorer or {},
        settings,
        repeat_count=repeat_count,
    )


def component(result, stage):
    return next(item for item in result["components"] if item["stage"] == stage)


def test_retrieval_preview_prices_real_query_and_all_repeats_without_llm_price():
    result = preview(
        [{"case_type": "retrieval", "query": "test", "source_refs": [{"doc_id": "d"}]}],
        repeat_count=2,
        embedding_cny_per_million=100000,
    )
    assert result["status"] == "estimated"
    assert result["first_attempt_cny"] == pytest.approx(0.8)
    assert result["retry_scenario_cny"] == pytest.approx(1.6)
    assert result["planned_executions"] == 2
    assert component(result, "generation")["status"] == "not_applicable"
    assert component(result, "scoring")["first_attempt_cny"] is None


def test_generation_includes_semantic_calls_and_obeys_cumulative_job_call_cap():
    result = preview(
        [
            {
                "case_type": "quiz",
                "user_input": "x",
                "question_count": 3,
                "source_policy": "topic",
            }
        ],
        repeat_count=2,
        llm_input_cny_per_million=1,
        llm_output_cny_per_million=2,
    )
    assert result["first_attempt_cny"] == pytest.approx(0.049156)
    assert result["retry_scenario_cny"] == pytest.approx(0.14337)
    assert component(result, "generation")["first_attempt_calls"] == 4
    assert component(result, "generation")["retry_scenario_calls"] == 10


def test_document_query_expansion_does_not_inflate_the_separate_generation_prompt():
    result = preview(
        [
            {
                "case_type": "quiz",
                "user_input": "x",
                "question_count": 3,
                "source_policy": "strict_docs",
                "source_refs": [{"doc_id": "d"}],
            }
        ],
        llm_input_cny_per_million=0,
        llm_output_cny_per_million=0,
        embedding_cny_per_million=0,
    )
    assert component(result, "generation")["first_attempt_input_tokens"] == 20194
    assert result["status"] == "estimated"
    assert result["first_attempt_cny"] == 0
    assert component(result, "generation")["prices"]["llm_input_cny_per_million"] == 0


def test_no_samples_or_missing_usage_stays_unknown():
    assert preview([])["status"] == "unknown"
    result = preview([{"case_type": "retrieval", "source_refs": [{"doc_id": "d"}]}])
    assert result["status"] == "unknown"
    assert result["first_attempt_cny"] is None


def test_single_goal_ablation_does_not_charge_for_catalog_subqueries():
    from app.services.evaluation_cost_preview import estimate_cost

    sample = {
        "case_type": "quiz",
        "user_input": "test",
        "question_count": 3,
        "source_refs": [{"doc_id": "d"}],
        "source_policy": "strict_docs",
    }
    result = estimate_cost(
        [sample],
        PipelineConfig(coverage_strategy="single-goal-v1"),
        {},
        Settings(_env_file=None, embedding_cny_per_million=1, enable_web_search=False),
        repeat_count=1,
    )
    retrieval = component(result, "retrieval")
    assert retrieval["first_attempt_input_tokens"] == 4
    assert retrieval["retry_scenario_calls"] == 4
    assert retrieval["retry_scenario_input_tokens"] == 16


@pytest.mark.parametrize("kind", ["retrieval", "quiz"])
def test_chat_reranking_uses_llm_token_prices_and_shared_call_cap(kind):
    from app.rag.providers.llm_reranker_config import llm_reranker_config
    from app.services.evaluation_cost_preview import estimate_cost

    settings = Settings(
        _env_file=None,
        llm_provider="anthropic",
        anthropic_model="claude-fixture",
        anthropic_api_key="test-only",
        llm_input_cny_per_million=1,
        llm_output_cny_per_million=2,
        llm_cache_read_cny_per_million=0.1,
        llm_cache_write_cny_per_million=1.2,
        rerank_call_cny=None,
        enable_web_search=False,
    )
    result = estimate_cost(
        [
            {
                "case_type": kind,
                "query": "test",
                "user_input": "test",
                "source_refs": [{"doc_id": "d"}],
            }
        ],
        PipelineConfig(retriever="bm25", reranker=llm_reranker_config(settings)),
        {},
        settings,
        repeat_count=2,
    )
    retrieval, generation = (
        component(result, "retrieval"),
        component(result, "generation"),
    )
    assert result["status"] == "estimated"
    assert retrieval["first_attempt_calls"] == 2
    assert retrieval["retry_scenario_calls"] == 4
    assert retrieval["first_attempt_input_tokens"] == 24000
    assert retrieval["first_attempt_output_tokens"] == 1024
    assert retrieval["first_attempt_cny"] == pytest.approx(0.026048)
    assert "rerank_call_cny" not in retrieval["prices"]
    if kind == "quiz":
        assert generation["first_attempt_calls"] == 4
        assert generation["retry_scenario_calls"] == 6
        assert (
            retrieval["retry_scenario_calls"] + generation["retry_scenario_calls"] == 10
        )
        assert "本版本未配置缓存计价" not in " ".join(generation["assumptions"])
        assert "缓存读写单价" in " ".join(generation["assumptions"])


def test_chat_ranking_cannot_treat_remote_per_call_price_as_a_chat_token_price():
    from app.rag.providers.llm_reranker_config import llm_reranker_config
    from app.services.evaluation_cost_preview import estimate_cost

    settings = Settings(
        _env_file=None, deepseek_api_key="test-only", rerank_call_cny=0.1
    )
    result = estimate_cost(
        [{"case_type": "retrieval", "query": "test", "source_refs": [{"doc_id": "d"}]}],
        PipelineConfig(retriever="bm25", reranker=llm_reranker_config(settings)),
        {},
        settings,
        repeat_count=1,
    )
    assert result["status"] == "unknown"
    assert component(result, "retrieval")["missing_prices"] == [
        "llm_input_cny_per_million",
        "llm_output_cny_per_million",
    ]


def test_missing_price_keeps_total_unknown_even_when_other_stages_are_priced():
    result = preview(
        [
            {
                "case_type": "quiz",
                "user_input": "x",
                "question_count": 3,
                "source_policy": "strict_docs",
                "source_refs": [{"doc_id": "d"}],
            }
        ],
        embedding_cny_per_million=1,
        llm_input_cny_per_million=1,
    )
    assert result["status"] == "unknown"
    assert result["first_attempt_cny"] is None
    assert result["retry_scenario_cny"] is None
    assert component(result, "retrieval")["status"] == "estimated"
    assert component(result, "generation")["missing_prices"] == [
        "llm_output_cny_per_million"
    ]


def test_scoring_uses_dated_token_prices_not_budget_or_reservation_ceiling():
    scorer = {
        "external_judge": {
            "max_input_tokens": 1000,
            "max_output_tokens": 100,
            "max_llm_calls": 32,
            "max_cost_cny": 99,
            "call_cost_ceiling_cny": 20,
            "price_table": {
                "effective_date": "2026-09-08",
                "input_cny_per_million": 10,
                "output_cny_per_million": 20,
            },
        }
    }
    samples = [
        {
            "case_type": "quiz",
            "user_input": "x",
            "question_count": 3,
            "source_policy": "strict_docs",
            "source_refs": [{"doc_id": "d"}],
        }
    ]
    result = preview(samples, scorer=scorer, repeat_count=2)
    scoring = component(result, "scoring")
    assert scoring["first_attempt_cny"] == pytest.approx(0.144)
    assert scoring["retry_scenario_cny"] == pytest.approx(0.288)
    scorer["external_judge"].update(max_cost_cny=1, call_cost_ceiling_cny=0.02)
    assert (
        component(preview(samples, scorer=scorer, repeat_count=2), "scoring") == scoring
    )


def test_local_policy_and_uncited_topic_scoring_are_not_applicable():
    result = preview([{"case_type": "policy"}], repeat_count=2)
    assert result["status"] == "not_applicable"
    assert result["first_attempt_cny"] is None
    assert all(item["status"] == "not_applicable" for item in result["components"])
    topic = preview(
        [
            {
                "case_type": "quiz",
                "user_input": "x",
                "source_policy": "topic",
                "question_count": 3,
            }
        ],
        scorer={"external_judge": {}},
    )
    assert component(topic, "scoring")["status"] == "not_applicable"


def test_web_or_legacy_usage_is_unknown_instead_of_invented():
    from app.services.evaluation_cost_preview import estimate_cost

    sample = {
        "case_type": "quiz",
        "user_input": "x",
        "source_policy": "topic",
        "question_count": 3,
    }
    result = estimate_cost(
        [sample],
        PipelineConfig(),
        {},
        Settings(
            _env_file=None,
            enable_web_search=True,
            tavily_api_key="fixture",
            llm_input_cny_per_million=1,
            llm_output_cny_per_million=1,
            search_call_cny=0,
            embedding_cny_per_million=0,
        ),
        repeat_count=1,
    )
    assert component(result, "retrieval")["status"] == "unknown"
    assert result["first_attempt_cny"] is None
    result = estimate_cost(
        [sample],
        PipelineConfig(pipeline_version="legacy-summary-b0"),
        {},
        Settings(_env_file=None, enable_web_search=False),
        repeat_count=1,
    )
    assert component(result, "generation")["status"] == "unknown"


@pytest.mark.asyncio
async def test_preview_is_owner_scoped_read_only_and_rejects_budget_as_estimate(
    learner,
):
    from app.core.db import execute, fetch_one
    from app.core.values import digest, dump, uid

    api, session = learner
    owner = session["user"]["id"]
    dataset_id = uid("dataset")
    manifest, samples = {"state": "frozen"}, [{"case_type": "policy"}]
    await execute(
        "INSERT INTO eval_datasets(dataset_id,version,owner_id,name,status,revision,manifest_json,samples_json,checksum) "
        "VALUES(%s,1,%s,'preview','frozen',1,%s,%s,%s)",
        (
            dataset_id,
            owner,
            dump(manifest),
            dump(samples),
            digest(dump({"manifest": manifest, "samples": samples})),
        ),
    )
    params = {
        "dataset_id": dataset_id,
        "dataset_version": 1,
        "pipeline_id": "dense-v1",
        "repeat_count": 2,
    }
    path = "/api/v1/eval/runs/estimate"
    assert (await api.get(path, params=params)).status_code == 403
    await execute("UPDATE users SET role='evaluator' WHERE id=%s", (owner,))
    before = await fetch_one(
        "SELECT (SELECT COUNT(*) FROM eval_runs WHERE owner_id=%s) AS runs, "
        "(SELECT COUNT(*) FROM provider_calls WHERE owner_id=%s) AS calls, "
        "(SELECT COUNT(*) FROM quiz_tasks WHERE user_id=%s) AS jobs, "
        "(SELECT COUNT(*) FROM budget_accounts) AS budgets",
        (owner, owner, owner),
    )
    response = await api.get(path, params=params)
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "not_applicable"
    assert response.json()["data"]["planned_executions"] == 2
    assert (
        await api.get(path, params={**params, "max_cost_cny": 999})
    ).status_code == 422
    assert (
        await api.get(path, params={**params, "dataset_id": "another-owner"})
    ).status_code == 404
    import httpx
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as other:
        registered_session, _ = await register_email_account(
            other, nickname="另一评测者"
        )
        await execute(
            "UPDATE users SET role='evaluator' WHERE id=%s",
            (registered_session["user"]["id"],),
        )
        assert (await other.get(path, params=params)).status_code == 404
    assert (
        await api.get(path, params={**params, "repeat_count": 3})
    ).status_code == 422
    await execute(
        "UPDATE eval_datasets SET status='draft' WHERE dataset_id=%s", (dataset_id,)
    )
    assert (await api.get(path, params=params)).status_code == 409
    after = await fetch_one(
        "SELECT (SELECT COUNT(*) FROM eval_runs WHERE owner_id=%s) AS runs, "
        "(SELECT COUNT(*) FROM provider_calls WHERE owner_id=%s) AS calls, "
        "(SELECT COUNT(*) FROM quiz_tasks WHERE user_id=%s) AS jobs, "
        "(SELECT COUNT(*) FROM budget_accounts) AS budgets",
        (owner, owner, owner),
    )
    assert after == before
