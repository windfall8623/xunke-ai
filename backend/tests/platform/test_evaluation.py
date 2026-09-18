import uuid
from datetime import timedelta

import pytest
import pytest_asyncio


def policy_dataset():
    return {
        "name": "Policy fixture",
        "manifest": {
            "state": "draft",
            "annotation_version": "v1",
            "sources": [],
            "review": {
                "checklist": {
                    "source_rights": True,
                    "spans": True,
                    "family_split": True,
                    "answerability": True,
                    "second_review": True,
                }
            },
        },
        "samples": [
            {
                "schema_version": "1",
                "sample_id": "policy-one",
                "case_type": "policy",
                "family_ids": ["synthetic-family"],
                "split": "dev",
                "source_refs": [],
                "tags": ["synthetic"],
                "harness": {"synthetic_only": True, "resources": []},
                "scenario": "cross_owner",
                "expected_status": "rejected",
                "annotation": {"provenance": "model_draft", "review_records": []},
            }
        ],
    }


@pytest.mark.asyncio
async def test_dataset_roles_review_freeze_and_no_frozen_overwrite(learner):
    api, session = learner
    assert (await api.get("/api/v1/eval/datasets")).status_code == 403
    from app.core.db import execute

    await execute(
        "UPDATE users SET role='evaluator' WHERE id=%s", (session["user"]["id"],)
    )
    response = await api.post("/api/v1/eval/datasets", json=policy_dataset())
    assert response.status_code == 201, response.text
    dataset = response.json()["data"]
    path = f"/api/v1/eval/datasets/{dataset['dataset_id']}/versions/1"
    no_review = await api.post(path + "/freeze", json={"expected_revision": 1})
    assert no_review.status_code == 409
    reviewed = await api.post(
        path + "/samples/policy-one/review",
        json={
            "expected_revision": 1,
            "verdict": "approved",
            "comment": "Reviewed synthetic fixture",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    frozen = await api.post(path + "/freeze", json={"expected_revision": 2})
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["data"]["status"] == "frozen"
    assert (
        frozen.json()["data"]["manifest"]["release_gold_status"]
        == "provisional_single_review"
    )
    edited = await api.patch(path, json={"revision": 3, "samples": []})
    assert edited.status_code == 409


@pytest.mark.asyncio
async def test_eval_run_idempotency_role_scope_and_cancel(learner):
    api, session = learner
    from app.core.db import execute, fetch_one

    await execute(
        "UPDATE users SET role='admin' WHERE id=%s", (session["user"]["id"],)
    )
    r = await api.post("/api/v1/eval/datasets", json=policy_dataset())
    dataset = r.json()["data"]
    path = f"/api/v1/eval/datasets/{dataset['dataset_id']}/versions/1"
    await api.post(
        path + "/samples/policy-one/review",
        json={"expected_revision": 1, "verdict": "approved", "comment": "Reviewed"},
    )
    await api.post(path + "/freeze", json={"expected_revision": 2})
    before = await fetch_one(
        "SELECT total_xp FROM users WHERE id=%s", (session["user"]["id"],)
    )
    body = {
        "dataset_id": dataset["dataset_id"],
        "dataset_version": 1,
        "pipeline_id": "dense-v1",
        "repeat_count": 1,
        "max_cost_cny": 2,
    }
    headers = {"Idempotency-Key": uuid.uuid4().hex}
    first = await api.post("/api/v1/eval/runs", json=body, headers=headers)
    assert first.status_code == 202, first.text
    run = first.json()["data"]
    second = await api.post("/api/v1/eval/runs", json=body, headers=headers)
    assert second.json()["data"]["run_id"] == run["run_id"]
    bad = await api.post(
        "/api/v1/eval/runs", json={**body, "repeat_count": 2}, headers=headers
    )
    assert bad.status_code == 409
    await execute(
        "UPDATE users SET role='evaluator' WHERE id=%s", (session["user"]["id"],)
    )
    for key in (headers["Idempotency-Key"], uuid.uuid4().hex):
        denied = await api.post(
            "/api/v1/eval/runs", json=body, headers={"Idempotency-Key": key}
        )
        assert denied.status_code == 403, denied.text
        assert denied.json()["error_code"] == "system_model_admin_required"
    path = f"/api/v1/eval/runs/{run['run_id']}"
    assert (await api.get(path)).status_code == 200
    assert (await api.get(path + "/export")).status_code == 200
    denied_resume = await api.post(path + "/resume")
    assert denied_resume.status_code == 403
    assert denied_resume.json()["error_code"] == "system_model_admin_required"
    cancel = await api.post(path + "/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["data"]["status"] == "cancelled"
    assert (
        await fetch_one(
            "SELECT total_xp FROM users WHERE id=%s", (session["user"]["id"],)
        )
        == before
    )
    sessions = await fetch_one(
        "SELECT COUNT(*) AS n FROM quiz_sessions WHERE user_id=%s",
        (session["user"]["id"],),
    )
    assert sessions["n"] == 0


@pytest_asyncio.fixture
async def quiz_result(learner):
    from rag_eval.metrics import score_sample

    from app.core.db import execute
    from app.core.values import digest, dump, now, uid

    api, session = learner
    owner = session["user"]["id"]
    await execute("UPDATE users SET role='evaluator' WHERE id=%s", (owner,))
    dataset_id, run_id, result_id = uid("dataset"), uid("eval"), uid("result")
    sample = {
        "sample_id": "quiz-review",
        "case_type": "quiz",
        "family_ids": ["review-family"],
        "split": "locked_test",
        "source_refs": [],
        "source_policy": "topic",
        "question_count": 3,
        "user_input": "Synthetic fixture facts",
        "expected_outcome": "generate",
        "source_sufficient": True,
        "annotation": {
            "review_records": [
                {
                    "reviewer_id": str(owner),
                    "provenance": "human",
                    "decision": "approved",
                    "reviewed_at": "2026-09-07T00:00:00Z",
                }
            ]
        },
    }
    manifest = {"state": "frozen", "sources": [], "annotation_version": "fixture-v1"}
    checksum = digest(dump({"manifest": manifest, "samples": [sample]}))
    config = {
        "dataset_hash": checksum,
        "annotation_version": "fixture-v1",
        "metric_version": "evidence-v1",
        "judge_config_hash": "deterministic-v1",
        "cache_protocol": "cold",
        "context_token_budget": 6000,
        "split": "locked_test",
        "repeat_count": 1,
        "dataset_state": "frozen",
        "gold_reviewed": True,
        "formal_gold_eligible": True,
        "judge_calibrated": False,
        "protocol_frozen": True,
        "planned_sample_ids": ["quiz-review"],
        "scoring_config": {
            "metric_version": "evidence-v1",
            "semantic_judge": "disabled",
        },
    }
    questions = [
        {
            "question_id": f"q{i}",
            "type": "single_choice",
            "stem": f"Fixture fact {i}?",
            "options": [
                {"id": "A", "text": f"Fact {i}"},
                {"id": "B", "text": "Incorrect fixture"},
            ],
            "answer": ["A"],
            "explanation": f"Fixture fact {i}.",
            "citation_refs": [],
        }
        for i in range(1, 4)
    ]
    artifact = {
        "schema_version": "1",
        "case_type": "quiz",
        "sample_id": "quiz-review",
        "status": "completed",
        "evidence": [],
        "questions": questions,
        "usage": {
            "context_tokens": 0,
            "calls": [
                {
                    "call_id": "generation-fixture",
                    "stage": "generation",
                    "status": "completed",
                    "cost_cny": 0.2,
                    "cost_status": "estimated",
                    "input_tokens": 10,
                    "output_tokens": 5,
                }
            ],
        },
    }
    metrics = score_sample(sample, artifact)
    await execute(
        "INSERT INTO eval_datasets(dataset_id,version,owner_id,name,status,manifest_json,samples_json,checksum) VALUES(%s,1,%s,'Review fixture','frozen',%s,%s,%s)",
        (dataset_id, owner, dump(manifest), dump([sample]), checksum),
    )
    await execute(
        "INSERT INTO eval_runs(run_id,owner_id,dataset_id,dataset_version,pipeline_id,manifest_json,request_hash,idempotency_key,status,repeat_count,max_cost_cny,deadline_at) VALUES(%s,%s,%s,1,'dense-v1',%s,%s,%s,'completed',1,2,%s)",
        (
            run_id,
            owner,
            dataset_id,
            dump(config),
            digest(run_id),
            run_id,
            now() + timedelta(hours=1),
        ),
    )
    await execute(
        "INSERT INTO eval_results(result_id,run_id,sample_id,repeat_index,case_type,sample_json,status,prediction_status,artifact_json,metrics_json) VALUES(%s,%s,'quiz-review',0,'quiz',%s,'completed','completed',%s,%s)",
        (result_id, run_id, dump(sample), dump(artifact), dump(metrics)),
    )
    await execute(
        "INSERT INTO provider_calls(call_id,operation_id,owner_id,mode,stage,status,usage_json) VALUES(%s,%s,%s,'evaluation','judge','completed',%s)",
        (
            f"judge-{result_id}",
            f"evalscore:{result_id}:1:fixture",
            owner,
            dump(
                {
                    "call_id": f"judge-{result_id}",
                    "stage": "judge",
                    "status": "completed",
                    "cost_cny": 0.3,
                    "cost_status": "estimated",
                    "input_tokens": 5,
                    "output_tokens": 2,
                }
            ),
        ),
    )
    return {
        "api": api,
        "owner": owner,
        "run_id": run_id,
        "result_id": result_id,
        "metrics": metrics,
        "artifact": artifact,
    }


@pytest.mark.asyncio
async def test_human_question_review_recomputes_unknowns_and_keeps_original_scores_and_costs(
    quiz_result,
):
    from rag_eval.quiz_rubric import SEMANTIC_METRICS

    from app.core.db import fetch_one
    from app.core.values import load

    fixture = quiz_result
    api = fixture["api"]
    path = (
        f"/api/v1/eval/runs/{fixture['run_id']}/results/{fixture['result_id']}/review"
    )
    assert fixture["metrics"]["answer_correctness"]["status"] == "error"
    response = await api.put(
        path,
        json={
            "expected_revision": 0,
            "verdict": "pass",
            "comment": "Synthetic review",
            "question_reviews": [
                {
                    "question_id": f"q{i}",
                    "decisions": dict.fromkeys(SEMANTIC_METRICS, True),
                }
                for i in range(1, 4)
            ],
        },
    )
    assert response.status_code == 200, response.text
    row = await fetch_one(
        "SELECT * FROM eval_results WHERE result_id=%s", (fixture["result_id"],)
    )
    metrics, review = load(row["metrics_json"]), load(row["review_json"])
    assert (
        metrics["answer_correctness"]["status"] == "ok"
        and metrics["answer_correctness"]["value"] == 1
    )
    assert metrics["total_cost_cny"]["value"] == 0.5
    assert review["automatic_metrics"] == fixture["metrics"]
    assert all(
        item["reviewer_id"] == str(fixture["owner"]) and item["question_hash"]
        for item in review["question_reviews"]
    )
    assert load(row["artifact_json"]) == fixture["artifact"]
    assert (
        await api.put(path, json={"expected_revision": 0, "verdict": "fail"})
    ).status_code == 409
    unchanged = await api.put(
        path,
        json={
            "expected_revision": 1,
            "verdict": "uncertain",
            "question_reviews": [
                {"question_id": "q1", "decisions": {"answer_correctness": None}}
            ],
        },
    )
    assert unchanged.status_code == 200, unchanged.text
    row = await fetch_one(
        "SELECT metrics_json,review_json FROM eval_results WHERE result_id=%s",
        (fixture["result_id"],),
    )
    assert load(row["metrics_json"])["answer_correctness"]["status"] == "error"
    assert len(load(row["review_json"])["previous_reviews"]) == 1


@pytest.mark.asyncio
async def test_question_review_rejects_unknown_ids_and_forged_reviewer_fields(
    quiz_result,
):
    fixture = quiz_result
    path = (
        f"/api/v1/eval/runs/{fixture['run_id']}/results/{fixture['result_id']}/review"
    )
    bad = await fixture["api"].put(
        path,
        json={
            "expected_revision": 0,
            "verdict": "pass",
            "question_reviews": [{"question_id": "missing", "decisions": {}}],
        },
    )
    assert bad.status_code == 422
    forged = await fixture["api"].put(
        path,
        json={
            "expected_revision": 0,
            "verdict": "pass",
            "question_reviews": [
                {"question_id": "q1", "reviewer_id": "other", "decisions": {}}
            ],
        },
    )
    assert forged.status_code == 422


@pytest.mark.asyncio
async def test_comparison_uses_real_units_and_reports_run_eligibility_reasons(
    quiz_result,
):
    fixture = quiz_result
    run = await fixture["api"].get(f"/api/v1/eval/runs/{fixture['run_id']}")
    assert run.status_code == 200, run.text
    assert run.json()["data"]["ineligibility_reasons"]
    response = await fixture["api"].get(
        "/api/v1/eval/compare",
        params={
            "baseline_run_id": fixture["run_id"],
            "candidate_run_id": fixture["run_id"],
            "exploratory": True,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["metrics"]["total_cost_cny"]["unit"] == "CNY"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outside_cost,expected", [(None, None), (3.0, False), (0.3, True)]
)
async def test_group_comparison_checks_cost_of_the_entire_run(
    quiz_result, outside_cost, expected
):
    import copy

    from app.core.db import execute, fetch_one
    from app.core.values import digest, dump, load, uid

    fixture = quiz_result
    row = await fetch_one(
        "SELECT * FROM eval_results WHERE result_id=%s", (fixture["result_id"],)
    )
    included = load(row["sample_json"])
    included["tags"] = ["pdf"]
    outside = {**copy.deepcopy(included), "sample_id": "outside-group", "tags": ["txt"]}
    metrics = load(row["metrics_json"])
    metrics["total_cost_cny"] = {
        "status": "error" if outside_cost is None else "ok",
        "value": outside_cost,
        "numerator": outside_cost or 0,
        "denominator": 1,
        "unit": "CNY",
        "unknown_count": int(outside_cost is None),
    }
    await execute(
        "UPDATE eval_results SET sample_json=%s WHERE result_id=%s",
        (dump(included), fixture["result_id"]),
    )
    await execute(
        "INSERT INTO eval_results(result_id,run_id,sample_id,repeat_index,case_type,sample_json,status,prediction_status,artifact_json,metrics_json) VALUES(%s,%s,'outside-group',0,'quiz',%s,'completed','completed',%s,%s)",
        (
            uid("result"),
            fixture["run_id"],
            dump(outside),
            row["artifact_json"],
            dump(metrics),
        ),
    )
    run = await fetch_one(
        "SELECT * FROM eval_runs WHERE run_id=%s", (fixture["run_id"],)
    )
    dataset = await fetch_one(
        "SELECT manifest_json FROM eval_datasets WHERE dataset_id=%s AND version=%s",
        (run["dataset_id"], run["dataset_version"]),
    )
    checksum = digest(
        dump(
            {"manifest": load(dataset["manifest_json"]), "samples": [included, outside]}
        )
    )
    await execute(
        "UPDATE eval_datasets SET samples_json=%s,checksum=%s WHERE dataset_id=%s AND version=%s",
        (
            dump([included, outside]),
            checksum,
            run["dataset_id"],
            run["dataset_version"],
        ),
    )
    manifest = load(run["manifest_json"])
    manifest.update(
        dataset_hash=checksum,
        planned_sample_ids=[included["sample_id"], outside["sample_id"]],
        cost_estimate={"max_cost_cny": 2, "kind": "conservative_ceiling"},
    )
    await execute(
        "UPDATE eval_runs SET manifest_json=%s WHERE run_id=%s",
        (dump(manifest), fixture["run_id"]),
    )
    response = await fixture["api"].get(
        "/api/v1/eval/compare",
        params={
            "baseline_run_id": fixture["run_id"],
            "candidate_run_id": fixture["run_id"],
            "exploratory": True,
            "group": "pdf",
        },
    )
    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["sample_count"] == 1
    assert report["metrics"]["total_cost_cny"]["candidate"]["value"] == 0.2
    assert report["cost_within_budget"] is expected
    if outside_cost is None:
        assert "candidate_cost_unknown" in report["ineligibility_reasons"]


@pytest.mark.asyncio
async def test_comparison_checks_legacy_manifest_limit_against_sql(quiz_result):
    from app.core.db import execute, fetch_one
    from app.core.values import dump, load

    fixture = quiz_result
    row = await fetch_one(
        "SELECT manifest_json FROM eval_runs WHERE run_id=%s", (fixture["run_id"],)
    )
    manifest = load(row["manifest_json"])
    manifest["cost_estimate"] = {"max_cost_cny": 100, "kind": "conservative_ceiling"}
    await execute(
        "UPDATE eval_runs SET manifest_json=%s WHERE run_id=%s",
        (dump(manifest), fixture["run_id"]),
    )
    response = await fixture["api"].get(
        "/api/v1/eval/compare",
        params={
            "baseline_run_id": fixture["run_id"],
            "candidate_run_id": fixture["run_id"],
            "exploratory": True,
        },
    )
    assert response.status_code == 200, response.text
    report = response.json()["data"]
    assert report["cost_within_budget"] is None
    assert "candidate_cost_limit_mismatch" in report["ineligibility_reasons"]


@pytest.mark.asyncio
async def test_new_run_freezes_cost_protocol_with_the_immutable_budget(learner):
    from app.core.db import execute, fetch_one

    api, session = learner
    await execute(
        "UPDATE users SET role='admin' WHERE id=%s", (session["user"]["id"],)
    )
    dataset_id = await frozen_policy(api)
    response = await api.post(
        "/api/v1/eval/runs",
        json={
            "dataset_id": dataset_id,
            "dataset_version": 1,
            "pipeline_id": "dense-v1",
            "repeat_count": 1,
            "max_cost_cny": 2.5,
        },
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert response.status_code == 202, response.text
    run = response.json()["data"]
    assert run["manifest"]["cost_protocol"] == {
        "version": "run-cost-v1",
        "currency": "CNY",
        "scope": "entire_run",
        "aggregation": "sum_all_attempts",
        "max_cost_cny": 2.5,
    }
    saved = await fetch_one(
        "SELECT max_cost_cny FROM eval_runs WHERE run_id=%s", (run["run_id"],)
    )
    assert (
        float(saved["max_cost_cny"]) == run["manifest"]["cost_protocol"]["max_cost_cny"]
    )


def test_b0_candidate_requires_and_uses_verified_archive(
    platform_settings, tmp_path, monkeypatch
):
    from app.services.evaluation_service import list_pipelines, pipeline_config
    from tests.rag.test_legacy_baseline import archive

    assert "legacy-summary-b0" not in {
        item["pipeline_id"] for item in list_pipelines()["items"]
    }
    path, checksum = archive(tmp_path)
    monkeypatch.setattr(platform_settings, "legacy_source_archive", str(path))
    monkeypatch.setattr(platform_settings, "legacy_source_archive_sha256", checksum)
    config = pipeline_config("legacy-summary-b0")
    assert config.legacy_source_archive_sha256 == checksum
    assert config.legacy_source_commit == platform_settings.legacy_source_commit


async def frozen_policy(api):
    created = (await api.post("/api/v1/eval/datasets", json=policy_dataset())).json()[
        "data"
    ]
    path = f"/api/v1/eval/datasets/{created['dataset_id']}/versions/1"
    await api.post(
        path + "/samples/policy-one/review",
        json={"expected_revision": 1, "verdict": "approved"},
    )
    response = await api.post(path + "/freeze", json={"expected_revision": 2})
    assert response.status_code == 200, response.text
    return created["dataset_id"]


@pytest.mark.asyncio
async def test_resume_rechecks_budget_stop_after_concurrent_state_change(
    learner, monkeypatch
):
    import asyncio

    from app.core.db import execute
    from app.services import evaluation_service as service

    api, session = learner
    owner = session["user"]["id"]
    await execute("UPDATE users SET role='admin' WHERE id=%s", (owner,))
    dataset_id = await frozen_policy(api)
    response = await api.post(
        "/api/v1/eval/runs",
        json={
            "dataset_id": dataset_id,
            "dataset_version": 1,
            "pipeline_id": "dense-v1",
            "repeat_count": 1,
            "max_cost_cny": 2,
        },
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    run_id = response.json()["data"]["run_id"]
    await api.post(f"/api/v1/eval/runs/{run_id}/cancel")
    reached, release = asyncio.Event(), asyncio.Event()
    original = service.authorized_run

    async def pause_after_read(*args, **kwargs):
        row = await original(*args, **kwargs)
        if not reached.is_set():
            reached.set()
            await release.wait()
        return row

    monkeypatch.setattr(service, "authorized_run", pause_after_read)
    resume = asyncio.create_task(api.post(f"/api/v1/eval/runs/{run_id}/resume"))
    await asyncio.wait_for(reached.wait(), 5)
    await execute(
        "UPDATE eval_runs SET status='failed',stop_reason='budget_exceeded' WHERE run_id=%s",
        (run_id,),
    )
    release.set()
    result = await asyncio.wait_for(resume, 5)
    assert result.status_code == 409, result.text
    assert result.json()["error_code"] == "run_not_resumable"


@pytest.mark.asyncio
async def test_concurrent_different_dataset_same_run_key_returns_conflict(
    learner, monkeypatch
):
    import asyncio

    from app.core.db import execute
    from app.services import evaluation_service as service

    api, session = learner
    await execute(
        "UPDATE users SET role='admin' WHERE id=%s", (session["user"]["id"],)
    )
    dataset_ids = [await frozen_policy(api), await frozen_policy(api)]
    original = service.execute
    reached = asyncio.Event()
    count = 0

    async def simultaneous_insert(sql, *args, **kwargs):
        nonlocal count
        if sql.startswith("INSERT INTO eval_runs"):
            count += 1
            if count == 2:
                reached.set()
            await asyncio.wait_for(reached.wait(), 5)
        return await original(sql, *args, **kwargs)

    monkeypatch.setattr(service, "execute", simultaneous_insert)
    headers = {"Idempotency-Key": uuid.uuid4().hex}
    outcomes = await asyncio.gather(
        *[
            api.post(
                "/api/v1/eval/runs",
                json={
                    "dataset_id": dataset_id,
                    "dataset_version": 1,
                    "pipeline_id": "dense-v1",
                    "repeat_count": 1,
                    "max_cost_cny": 2,
                },
                headers=headers,
            )
            for dataset_id in dataset_ids
        ],
        return_exceptions=True,
    )
    assert all(not isinstance(result, BaseException) for result in outcomes), outcomes
    assert sorted(result.status_code for result in outcomes) == [202, 409]


@pytest.mark.asyncio
async def test_judge_profiles_default_to_deterministic_without_external_configuration(
    learner,
):
    from app.core.db import execute

    api, session = learner
    await execute(
        "UPDATE users SET role='evaluator' WHERE id=%s", (session["user"]["id"],)
    )
    response = await api.get("/api/v1/eval/judges")
    assert response.status_code == 200, response.text
    assert [item["judge_profile_id"] for item in response.json()["data"]["items"]] == [
        "deterministic-v1"
    ]


@pytest.mark.asyncio
async def test_external_judge_selection_is_pinned_per_run_without_credentials(
    learner, platform_settings, tmp_path, monkeypatch
):
    import json

    from app.core.db import execute

    api, session = learner
    await execute(
        "UPDATE users SET role='admin' WHERE id=%s", (session["user"]["id"],)
    )
    config = {
        "enabled": True,
        "model": "fixture-model-v1",
        "base_url": "https://judge.example.test/v1",
        "ragas_version": "0.4.3",
        "prompt_version": "quiz-facts-v1",
        "prompt_hash": "a" * 64,
        "max_llm_calls": 20,
        "max_cost_cny": 1,
        "call_cost_ceiling_cny": 0.1,
        "max_input_tokens": 20000,
        "max_output_tokens": 512,
        "timeout_seconds": 30,
        "total_timeout_seconds": 300,
        "price_table": {
            "effective_date": "2026-09-07",
            "input_cny_per_million": 2,
            "output_cny_per_million": 4,
        },
        "calibrated": False,
    }
    target = tmp_path / "judge.json"
    target.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(platform_settings, "eval_judge_config_path", str(target))
    choices = (await api.get("/api/v1/eval/judges")).json()["data"]["items"]
    assert {item["judge_profile_id"] for item in choices} == {
        "deterministic-v1",
        "ragas-faithfulness-v1",
    }
    dataset_id = await frozen_policy(api)
    body = {
        "dataset_id": dataset_id,
        "dataset_version": 1,
        "pipeline_id": "dense-v1",
        "repeat_count": 1,
        "max_cost_cny": 2,
        "judge_profile_id": "ragas-faithfulness-v1",
    }
    headers = {"Idempotency-Key": uuid.uuid4().hex}
    response = await api.post("/api/v1/eval/runs", json=body, headers=headers)
    assert response.status_code == 202, response.text
    run = response.json()["data"]
    manifest = run["manifest"]
    assert manifest["judge_profile_id"] == "ragas-faithfulness-v1"
    assert manifest["scoring_config"]["external_judge"]["model"] == "fixture-model-v1"
    assert manifest["runtime_dependencies"]["backend"]["sha256"]
    assert manifest["runtime_dependencies"]["evaluation"]["sha256"]
    assert manifest["runtime_dependencies"]["evaluation_ragas"]["sha256"]
    assert "api_key" not in manifest["scoring_config"]["external_judge"]
    target.write_text(
        json.dumps({**config, "model": "changed-model"}), encoding="utf-8"
    )
    replay = (await api.post("/api/v1/eval/runs", json=body, headers=headers)).json()[
        "data"
    ]
    assert (
        replay["manifest"]["scoring_config"]["external_judge"]["model"]
        == "fixture-model-v1"
    )
    assert replay["manifest"]["judge_config_hash"] == manifest["judge_config_hash"]


@pytest.mark.asyncio
async def test_expired_run_retains_metric_view_but_cannot_resume_or_review(quiz_result):
    from app.core.db import execute

    fixture = quiz_result
    await execute(
        "UPDATE eval_runs SET manifest_json=JSON_SET(manifest_json,'$.raw_artifacts_status','expired','$.reproducible',false) WHERE run_id=%s",
        (fixture["run_id"],),
    )
    path = f"/api/v1/eval/runs/{fixture['run_id']}"
    shown = await fixture["api"].get(path)
    assert (
        shown.status_code == 200
        and "raw_artifacts_expired" in shown.json()["data"]["ineligibility_reasons"]
    )
    assert (await fixture["api"].get(path + "/results")).json()["data"]["items"][0][
        "metrics"
    ]
    resume = await fixture["api"].post(path + "/resume")
    assert (
        resume.status_code == 403
        and resume.json()["error_code"] == "system_model_admin_required"
    )
    review = await fixture["api"].put(
        path + f"/results/{fixture['result_id']}/review",
        json={"expected_revision": 0, "verdict": "pass"},
    )
    assert (
        review.status_code == 409
        and review.json()["error_code"] == "raw_artifacts_expired"
    )
    await execute("UPDATE users SET role='admin' WHERE id=%s", (fixture["owner"],))
    admin_resume = await fixture["api"].post(path + "/resume")
    assert (
        admin_resume.status_code == 409
        and admin_resume.json()["error_code"] == "raw_artifacts_expired"
    )
