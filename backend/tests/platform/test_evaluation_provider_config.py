import uuid

import pytest

from tests.platform.test_evaluation import policy_dataset


async def create_provider_run(learner):
    from app.core.db import execute

    api, session = learner
    await execute(
        "UPDATE users SET role='admin' WHERE id=%s", (session["user"]["id"],)
    )
    payload = policy_dataset()
    payload["samples"] = [
        {
            "schema_version": "1",
            "sample_id": "model-fixture",
            "case_type": "retrieval",
            "family_ids": ["model-fixture-family"],
            "split": "dev",
            "source_refs": [],
            "query": "No document has been selected",
            "expected_outcome": "unanswerable",
            "gold_evidence_groups": [],
            "annotation": {"provenance": "model_draft", "review_records": []},
        }
    ]
    created = await api.post("/api/v1/eval/datasets", json=payload)
    assert created.status_code == 201, created.text
    dataset_id = created.json()["data"]["dataset_id"]
    path = f"/api/v1/eval/datasets/{dataset_id}/versions/1"
    reviewed = await api.post(
        path + "/samples/model-fixture/review",
        json={"expected_revision": 1, "verdict": "approved"},
    )
    assert reviewed.status_code == 200, reviewed.text
    frozen = await api.post(path + "/freeze", json={"expected_revision": 2})
    assert frozen.status_code == 200, frozen.text
    body = {
        "dataset_id": dataset_id,
        "dataset_version": 1,
        "pipeline_id": "dense-v1",
        "repeat_count": 1,
        "max_cost_cny": 2,
    }
    headers = {"Idempotency-Key": uuid.uuid4().hex}
    response = await api.post("/api/v1/eval/runs", json=body, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()["data"], body, headers


@pytest.mark.asyncio
async def test_evaluation_freezes_selected_claude_identity_and_replays_original(
    learner, platform_settings
):
    from app.core.values import digest, dump

    platform_settings.llm_provider = "anthropic"
    platform_settings.anthropic_model = "claude-fixture-v1"
    platform_settings.anthropic_base_url = "https://claude.example.test/v1/"
    platform_settings.anthropic_api_key = "fixture-secret-anthropic"
    platform_settings.deepseek_api_key = "fixture-secret-deepseek"
    platform_settings.llm_input_cny_per_million = 2
    platform_settings.llm_output_cny_per_million = 4
    run, body, headers = await create_provider_run(learner)
    manifest = run["manifest"]
    provider = manifest["provider_config"]
    assert provider.get("generator_provider") == "anthropic"
    assert provider["generator_model"] == "claude-fixture-v1"
    assert provider["generator_endpoint_hash"] == digest("https://claude.example.test")
    assert manifest["pipeline_config"]["generator_model"] == "claude-fixture-v1"
    assert provider["pricing"]["llm_input_cny_per_million"] == 2
    assert provider["pricing"]["llm_output_cny_per_million"] == 4
    assert "fixture-secret" not in dump(manifest)

    platform_settings.anthropic_model = "claude-fixture-v2"
    platform_settings.llm_input_cny_per_million = 3
    api, _ = learner
    replay = await api.post("/api/v1/eval/runs", json=body, headers=headers)
    assert replay.status_code == 202, replay.text
    replayed = replay.json()["data"]
    assert replayed["run_id"] == run["run_id"]
    assert replayed["manifest"]["provider_config"] == provider
    assert (
        replayed["manifest"]["pipeline_config_hash"] == manifest["pipeline_config_hash"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["provider", "model", "endpoint", "pricing", "pricing_version"]
)
async def test_owner_rejects_frozen_run_when_provider_configuration_changes(
    learner, platform_settings, change
):
    from app.core.db import fetch_one
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.engine import RagEngine
    from app.services.source_service import reauthorize_scope
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding

    platform_settings.llm_provider = "deepseek"
    platform_settings.deepseek_model = "deepseek-fixture-v1"
    platform_settings.deepseek_base_url = "https://deepseek.example.test"
    run, _, _ = await create_provider_run(learner)
    job = await fetch_one(
        "SELECT task_id FROM quiz_tasks WHERE kind='eval_sample' "
        "AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.run_id'))=%s",
        (run["run_id"],),
    )
    if change == "provider":
        # Same model and endpoint: the transport/provider identity still matters.
        platform_settings.llm_provider = "openai_compatible"
        platform_settings.llm_model = platform_settings.deepseek_model
        platform_settings.llm_base_url = platform_settings.deepseek_base_url
    elif change == "model":
        platform_settings.deepseek_model = "deepseek-fixture-v2"
    elif change == "endpoint":
        platform_settings.deepseek_base_url = "https://other.example.test"
    elif change == "pricing":
        platform_settings.llm_input_cny_per_million = 7
    else:
        platform_settings.pricing_version = "changed-price-table"
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(store, FixtureEmbedding(), None, reauthorize_scope)
        )
        assert await worker.run_once(task_id=job["task_id"])
    result = await fetch_one(
        "SELECT status,error_code FROM quiz_tasks WHERE task_id=%s", (job["task_id"],)
    )
    assert result == {
        "status": "failed",
        "error_code": "provider_configuration_changed",
    }
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM provider_calls WHERE operation_id=%s",
            (job["task_id"],),
        )
    )["n"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_provider", ["deepseek", "anthropic"])
@pytest.mark.parametrize("trailing_slash", [False, True])
async def test_legacy_manifest_without_provider_means_only_deepseek(
    learner, platform_settings, selected_provider, trailing_slash
):
    from app.core.db import execute, fetch_one
    from app.core.values import digest, dump
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.engine import RagEngine
    from app.services.source_service import reauthorize_scope
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding

    platform_settings.llm_provider = "deepseek"
    platform_settings.deepseek_model = "shared-model-fixture"
    platform_settings.deepseek_base_url = "https://gateway.example.test"
    if trailing_slash:
        platform_settings.deepseek_base_url += "/"
    run, _, _ = await create_provider_run(learner)
    manifest = run["manifest"]
    manifest["provider_config"].pop("generator_provider", None)
    manifest["provider_config"]["generator_endpoint_hash"] = digest(
        platform_settings.deepseek_base_url
    )
    # The API view omits scopes. Keep the original frozen scopes in storage.
    await execute(
        "UPDATE eval_runs SET manifest_json=JSON_SET(manifest_json,'$.provider_config',CAST(%s AS JSON)) WHERE run_id=%s",
        (dump(manifest["provider_config"]), run["run_id"]),
    )
    job = await fetch_one(
        "SELECT task_id FROM quiz_tasks WHERE kind='eval_sample' "
        "AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.run_id'))=%s",
        (run["run_id"],),
    )
    platform_settings.llm_provider = selected_provider
    platform_settings.anthropic_model = platform_settings.deepseek_model
    platform_settings.anthropic_base_url = platform_settings.deepseek_base_url
    # Rotating credentials alone must not invalidate frozen public identity.
    platform_settings.deepseek_api_key = "rotated-fixture-key"
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(store, FixtureEmbedding(), None, reauthorize_scope)
        )
        assert await worker.run_once(task_id=job["task_id"])
    result = await fetch_one(
        "SELECT status,error_code FROM quiz_tasks WHERE task_id=%s", (job["task_id"],)
    )
    if selected_provider == "deepseek":
        assert result == {"status": "completed", "error_code": None}
    else:
        assert result == {
            "status": "failed",
            "error_code": "provider_configuration_changed",
        }
