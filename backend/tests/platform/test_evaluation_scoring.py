"""Real MySQL and HTTP scoring-control tests; no external models or production data."""

import asyncio
import socket
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.db import execute, fetch_all, fetch_one, insert
from app.core.errors import AppError
from app.core.values import digest, dump, load, now, uid

PREFIX = "/api/v1/internal/eval/scoring"


@pytest.mark.parametrize("provider", [[], {}, None, 1])
def test_invalid_judge_provider_type_is_a_validation_error(provider):
    from app.services.evaluation_scoring import _call_payload

    with pytest.raises(AppError) as caught:
        _call_payload(
            {
                "call_id": "invalid-provider",
                "stage": "judge",
                "status": "reserved",
                "provider": provider,
            }
        )
    assert caught.value.status == 422


@pytest_asyncio.fixture
async def scoring_setup(database, platform_settings):
    from app.api.v1.routes.internal_eval import router

    owner = await insert(
        "INSERT INTO users(nickname,role) VALUES(%s,'evaluator')",
        ("Scoring integration fixture",),
    )
    dataset_id, run_id, result_id = uid("dataset"), uid("eval"), uid("result")
    sample = {
        "schema_version": "1",
        "sample_id": "policy-one",
        "case_type": "policy",
        "family_ids": [f"family-{owner}"],
        "split": "dev",
        "source_refs": [],
        "tags": ["synthetic"],
        "harness": {"synthetic_only": True, "resources": []},
        "expected_status": "denied",
        "expected_error_code": "forbidden",
        "annotation": {
            "provenance": "test_fixture",
            "review_records": [
                {
                    "reviewer_id": str(owner),
                    "reviewed_at": "2026-09-07T01:00:00Z",
                    "decision": "approved",
                    "independent": True,
                    "provenance": "human",
                }
            ],
        },
    }
    manifest = {
        "schema_version": "1",
        "dataset_id": dataset_id,
        "version": 1,
        "revision": 1,
        "state": "frozen",
        "annotation_version": "test-v1",
        "sources": [],
        "release_gold_status": "provisional_single_review",
        "review": {
            "checklist": {
                "source_rights": True,
                "spans": True,
                "family_split": True,
                "answerability": True,
                "second_review": False,
            }
        },
    }
    checksum = digest(dump({"manifest": manifest, "samples": [sample]}))
    run_manifest = {
        "dataset_hash": checksum,
        "metric_version": "evidence-v1",
        "judge_config_hash": "deterministic-v1",
        "context_token_budget": 6000,
    }
    artifact = {
        "schema_version": "1",
        "sample_id": "policy-one",
        "case_type": "policy",
        "status": "completed",
        "usage": {"calls": []},
        "observations": {
            "actual_status": "denied",
            "error_code": "forbidden",
            "unauthorized_source_count": 0,
            "production_side_effect_count": 0,
            "stale_publish_count": 0,
        },
    }
    await execute(
        "INSERT INTO eval_datasets(dataset_id,version,owner_id,name,status,manifest_json,samples_json,checksum) VALUES(%s,1,%s,'Scoring fixture','frozen',%s,%s,%s)",
        (dataset_id, owner, dump(manifest), dump([sample]), checksum),
    )
    await execute(
        "INSERT INTO eval_runs(run_id,owner_id,dataset_id,dataset_version,pipeline_id,manifest_json,request_hash,idempotency_key,status,repeat_count,max_cost_cny,deadline_at) VALUES(%s,%s,%s,1,'dense-v1',%s,%s,%s,'scoring',1,2,%s)",
        (
            run_id,
            owner,
            dataset_id,
            dump(run_manifest),
            digest(run_id),
            run_id,
            now() + timedelta(minutes=10),
        ),
    )
    await execute(
        "INSERT INTO eval_results(result_id,run_id,sample_id,repeat_index,case_type,sample_json,status,prediction_status,artifact_json) VALUES(%s,%s,'policy-one',0,'policy',%s,'pending_scoring','completed',%s)",
        (result_id, run_id, dump(sample), dump(artifact)),
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    @app.exception_handler(AppError)
    async def error_handler(request: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status,
            content={"error_code": exc.code, "message": exc.message},
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {platform_settings.eval_worker_token}"},
    ) as api:
        yield {
            "api": api,
            "app": app,
            "owner": owner,
            "dataset_id": dataset_id,
            "run_id": run_id,
            "result_id": result_id,
            "sample": sample,
            "artifact": artifact,
            "manifest": manifest,
            "settings": platform_settings,
        }
    # Scope cleanup to the generated run only; shared test DB may serve other suites.
    await execute(
        "DELETE FROM provider_calls WHERE owner_id=%s AND mode='evaluation'", (owner,)
    )
    await execute(
        "DELETE FROM budget_reservations WHERE operation_id LIKE %s",
        (f"evalscore:{result_id}:%",),
    )
    await execute(
        "DELETE FROM budget_accounts WHERE account_key=%s", (f"eval_run:{run_id}:cny",)
    )
    await execute("DELETE FROM eval_results WHERE run_id=%s", (run_id,))
    await execute("DELETE FROM eval_runs WHERE run_id=%s", (run_id,))
    await execute("DELETE FROM eval_datasets WHERE dataset_id=%s", (dataset_id,))


async def claim(setup, worker="worker-a"):
    response = await setup["api"].post(
        PREFIX + "/claim",
        json={"worker_id": worker, "run_id": setup["run_id"], "lease_seconds": 30},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


def fence(payload):
    return {"lease_token": payload["lease_token"], "attempt": payload["attempt"]}


def scores(value=1):
    return {
        "authorization_safety": {
            "status": "ok",
            "value": value,
            "numerator": value,
            "denominator": 1,
            "unit": "ratio",
            "metric_version": "evidence-v1",
            "unknown_count": 0,
        }
    }


@pytest.mark.asyncio
async def test_internal_routes_require_service_bearer_without_browser_csrf(
    scoring_setup,
):
    api = scoring_setup["api"]
    response = await api.post(
        PREFIX + "/claim",
        json={"worker_id": "x"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401
    assert (await claim(scoring_setup))["sample"]["sample_id"] == "policy-one"


@pytest.mark.asyncio
async def test_concurrent_claims_have_one_lease_and_one_result_identity(scoring_setup):
    api = scoring_setup["api"]
    responses = await asyncio.gather(
        *[
            api.post(
                PREFIX + "/claim",
                json={"worker_id": worker, "run_id": scoring_setup["run_id"]},
            )
            for worker in ("a", "b")
        ]
    )
    assert sorted(response.status_code for response in responses) == [200, 204]
    row = await fetch_one(
        "SELECT * FROM eval_results WHERE result_id=%s", (scoring_setup["result_id"],)
    )
    assert row["scoring_attempt"] == 1 and row["status"] == "scoring"


@pytest.mark.asyncio
async def test_expired_lease_cannot_overwrite_new_attempt(scoring_setup):
    first = await claim(scoring_setup)
    await execute(
        "UPDATE eval_results SET scoring_expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE result_id=%s",
        (scoring_setup["result_id"],),
    )
    second = await claim(scoring_setup, "worker-b")
    assert second["attempt"] == 2
    url = PREFIX + f"/{scoring_setup['result_id']}/complete"
    stale = await scoring_setup["api"].post(
        url, json={**fence(first), "metrics": scores(0)}
    )
    assert stale.status_code == 409
    current = await scoring_setup["api"].post(
        url, json={**fence(second), "metrics": scores(1)}
    )
    assert current.status_code == 200, current.text
    replay = await scoring_setup["api"].post(
        url, json={**fence(second), "metrics": scores(1)}
    )
    assert replay.status_code == 200
    row = await fetch_one(
        "SELECT metrics_json,status FROM eval_results WHERE result_id=%s",
        (scoring_setup["result_id"],),
    )
    assert (
        load(row["metrics_json"])["authorization_safety"]["value"] == 1
        and row["status"] == "completed"
    )


@pytest.mark.asyncio
async def test_cancel_and_source_revoke_fence_publication(scoring_setup):
    lease = await claim(scoring_setup)
    await execute(
        "UPDATE eval_datasets SET status='revoked' WHERE dataset_id=%s",
        (scoring_setup["dataset_id"],),
    )
    response = await scoring_setup["api"].post(
        PREFIX + f"/{scoring_setup['result_id']}/complete",
        json={**fence(lease), "metrics": scores()},
    )
    assert response.status_code == 409
    row = await fetch_one(
        "SELECT metrics_json FROM eval_results WHERE result_id=%s",
        (scoring_setup["result_id"],),
    )
    assert row["metrics_json"] is None


@pytest.mark.asyncio
async def test_failure_attempts_are_bounded_and_history_is_retained(scoring_setup):
    for index in range(2):
        lease = await claim(scoring_setup)
        response = await scoring_setup["api"].post(
            PREFIX + f"/{scoring_setup['result_id']}/fail",
            json={**fence(lease), "error_code": "scoring_error"},
        )
        assert response.status_code == 200, response.text
    exhausted = await scoring_setup["api"].post(
        PREFIX + "/claim",
        json={"worker_id": "third", "run_id": scoring_setup["run_id"]},
    )
    assert exhausted.status_code == 204
    row = await fetch_one(
        "SELECT * FROM eval_results WHERE result_id=%s", (scoring_setup["result_id"],)
    )
    assert row["scoring_attempt"] == 2 and row["status"] == "failed"
    assert (
        len(
            [
                event
                for event in load(row["attempts_json"])
                if event["event"] == "scoring_failed"
            ]
        )
        == 2
    )


@pytest.mark.asyncio
async def test_retry_claim_contains_previous_judge_usage_without_private_journal_fields(
    scoring_setup,
):
    first = await claim(scoring_setup)
    endpoint = PREFIX + f"/{scoring_setup['result_id']}"
    response = await scoring_setup["api"].post(
        endpoint + "/calls",
        json={
            **fence(first),
            "call": {
                "call_id": "previous-timeout",
                "stage": "judge",
                "status": "reserved",
                "reserved_cost_cny": 0.2,
            },
        },
    )
    assert response.status_code == 200, response.text
    await scoring_setup["api"].post(
        endpoint + "/fail", json={**fence(first), "error_code": "worker_unavailable"}
    )
    next_claim = await claim(scoring_setup)
    history = next_claim["previous_judge_calls"]
    assert len(history) == 1 and history[0]["reserved_cost_cny"] == 0.2
    assert history[0]["attempt"] == 1
    assert "lease_fingerprint" not in history[0] and "events" not in history[0]


@pytest.mark.asyncio
async def test_call_reservations_unknown_cost_and_settlement_are_idempotent(
    scoring_setup,
):
    lease = await claim(scoring_setup)
    url = PREFIX + f"/{scoring_setup['result_id']}/calls"
    reserved = {
        "call_id": "judge-1",
        "attempt": 1,
        "stage": "judge",
        "provider": "anthropic",
        "status": "reserved",
        "reserved_cost_cny": 0.5,
        "cost_status": "unknown",
        "cost_cny": None,
    }
    for _ in range(2):
        response = await scoring_setup["api"].post(
            url, json={**fence(lease), "call": reserved}
        )
        assert response.status_code == 200, response.text
    timeout = {**reserved, "status": "timeout"}
    assert (
        await scoring_setup["api"].post(url, json={**fence(lease), "call": timeout})
    ).status_code == 200
    account_key = f"eval_run:{scoring_setup['run_id']}:cny"
    account = await fetch_one(
        "SELECT used,reserved FROM budget_accounts WHERE account_key=%s", (account_key,)
    )
    assert account["reserved"] == Decimal("0.5") and account["used"] == 0
    cost_reservation = await fetch_one(
        "SELECT accounts_json FROM budget_reservations WHERE operation_id LIKE %s AND resource_type='cny'",
        (f"evalscore:{scoring_setup['result_id']}:%",),
    )
    assert f"evaluation:global:{now().date().isoformat()}:cny" in load(
        cost_reservation["accounts_json"]
    )
    blocked = await scoring_setup["api"].post(
        url,
        json={
            **fence(lease),
            "call": {**reserved, "call_id": "judge-2", "reserved_cost_cny": 1.6},
        },
    )
    assert blocked.status_code == 429
    run = await fetch_one(
        "SELECT status,stop_reason FROM eval_runs WHERE run_id=%s",
        (scoring_setup["run_id"],),
    )
    assert run == {"status": "failed", "stop_reason": "budget_exceeded"}
    settled = {
        **reserved,
        "status": "completed",
        "cost_cny": 0.1,
        "cost_status": "estimated",
        "input_tokens": 10,
        "output_tokens": 5,
        "input_token_details": {"cache_read": 3, "cache_creation": 2},
        "model": "claude-configured-alias",
        "provider_model": "claude-returned-model",
    }
    for _ in range(2):
        response = await scoring_setup["api"].post(
            url, json={**fence(lease), "call": settled}
        )
        assert response.status_code == 200, response.text
    account = await fetch_one(
        "SELECT used,reserved FROM budget_accounts WHERE account_key=%s", (account_key,)
    )
    assert account["used"] == Decimal("0.1") and account["reserved"] == 0
    ledger = await fetch_all(
        "SELECT usage_json FROM provider_calls WHERE owner_id=%s",
        (scoring_setup["owner"],),
    )
    assert len(ledger) == 1
    assert load(ledger[0]["usage_json"])["input_token_details"] == {
        "cache_read": 3,
        "cache_creation": 2,
    }
    assert [event["status"] for event in load(ledger[0]["usage_json"])["events"]] == [
        "reserved",
        "timeout",
        "completed",
    ]


@pytest.mark.asyncio
async def test_inflight_call_can_settle_after_cancellation_without_reauthorizing_sources(
    scoring_setup,
):
    lease = await claim(scoring_setup)
    url = PREFIX + f"/{scoring_setup['result_id']}/calls"
    reserved = {
        "call_id": "inflight",
        "stage": "judge",
        "status": "reserved",
        "reserved_cost_cny": 0.5,
        "cost_status": "unknown",
    }
    assert (
        await scoring_setup["api"].post(url, json={**fence(lease), "call": reserved})
    ).status_code == 200
    await execute(
        "UPDATE eval_runs SET status='cancelled' WHERE run_id=%s",
        (scoring_setup["run_id"],),
    )
    await execute(
        "UPDATE eval_results SET scoring_lease_token=NULL,status='cancelled' WHERE result_id=%s",
        (scoring_setup["result_id"],),
    )
    settled = {
        **reserved,
        "status": "completed",
        "cost_status": "estimated",
        "cost_cny": 0.2,
    }
    response = await scoring_setup["api"].post(
        url, json={**fence(lease), "call": settled}
    )
    assert response.status_code == 200, response.text
    account = await fetch_one(
        "SELECT used,reserved FROM budget_accounts WHERE account_key=%s",
        (f"eval_run:{scoring_setup['run_id']}:cny",),
    )
    assert account["used"] == Decimal("0.2") and account["reserved"] == 0
    wrong = {**fence(lease), "lease_token": "wrong-proof", "call": settled}
    assert (await scoring_setup["api"].post(url, json=wrong)).status_code == 409


@pytest.mark.asyncio
async def test_claim_rejects_tampered_frozen_dataset(scoring_setup):
    await execute(
        "UPDATE eval_datasets SET checksum=%s WHERE dataset_id=%s",
        ("0" * 64, scoring_setup["dataset_id"]),
    )
    response = await scoring_setup["api"].post(
        PREFIX + "/claim", json={"worker_id": "x", "run_id": scoring_setup["run_id"]}
    )
    assert response.status_code == 204
    row = await fetch_one(
        "SELECT status,error_code FROM eval_results WHERE result_id=%s",
        (scoring_setup["result_id"],),
    )
    assert (
        row["status"] == "failed" and row["error_code"] == "dataset_checksum_mismatch"
    )


@pytest.mark.asyncio
async def test_heartbeat_renews_current_lease_but_cannot_revive_expiry(scoring_setup):
    lease = await claim(scoring_setup)
    api = scoring_setup["api"]
    url = PREFIX + f"/{scoring_setup['result_id']}/heartbeat"
    response = await api.post(url, json={**fence(lease), "lease_seconds": 60})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["lease_expires_at"] > lease["lease_expires_at"]
    await execute(
        "UPDATE eval_results SET scoring_expires_at=UTC_TIMESTAMP(6)-INTERVAL 1 SECOND WHERE result_id=%s",
        (scoring_setup["result_id"],),
    )
    assert (
        await api.post(url, json={**fence(lease), "lease_seconds": 60})
    ).status_code == 409


@pytest.mark.asyncio
async def test_cancelled_run_rejects_scoring_and_new_model_calls(scoring_setup):
    lease = await claim(scoring_setup)
    await execute(
        "UPDATE eval_runs SET status='cancelled' WHERE run_id=%s",
        (scoring_setup["run_id"],),
    )
    url = PREFIX + f"/{scoring_setup['result_id']}"
    assert (
        await scoring_setup["api"].post(
            url + "/complete", json={**fence(lease), "metrics": scores()}
        )
    ).status_code == 409
    call = {
        "call_id": "late",
        "stage": "judge",
        "status": "reserved",
        "reserved_cost_cny": 0.1,
    }
    assert (
        await scoring_setup["api"].post(
            url + "/calls", json={**fence(lease), "call": call}
        )
    ).status_code == 409
    assert not await fetch_all(
        "SELECT call_id FROM provider_calls WHERE owner_id=%s",
        (scoring_setup["owner"],),
    )


@pytest.mark.asyncio
async def test_no_call_can_settle_without_reservation_or_log_private_prompt(
    scoring_setup,
):
    lease = await claim(scoring_setup)
    url = PREFIX + f"/{scoring_setup['result_id']}/calls"
    call = {
        "call_id": "unreserved",
        "stage": "judge",
        "status": "completed",
        "cost_cny": 0.1,
        "cost_status": "estimated",
    }
    assert (
        await scoring_setup["api"].post(url, json={**fence(lease), "call": call})
    ).status_code == 409
    private = {
        **call,
        "status": "reserved",
        "reserved_cost_cny": 0.2,
        "prompt": "do-not-store-private-source",
    }
    response = await scoring_setup["api"].post(
        url, json={**fence(lease), "call": private}
    )
    assert response.status_code == 422
    assert "do-not-store" not in response.text
    assert not await fetch_all(
        "SELECT call_id FROM provider_calls WHERE owner_id=%s",
        (scoring_setup["owner"],),
    )


@pytest.mark.asyncio
async def test_unknown_metric_must_not_publish_a_numeric_zero(scoring_setup):
    lease = await claim(scoring_setup)
    invalid = scores(0)
    invalid["authorization_safety"]["status"] = "error"
    response = await scoring_setup["api"].post(
        PREFIX + f"/{scoring_setup['result_id']}/complete",
        json={**fence(lease), "metrics": invalid},
    )
    assert response.status_code == 422
    row = await fetch_one(
        "SELECT metrics_json,status FROM eval_results WHERE result_id=%s",
        (scoring_setup["result_id"],),
    )
    assert row["metrics_json"] is None and row["status"] == "scoring"


@pytest.mark.asyncio
async def test_independent_worker_scores_over_real_http_without_learning_writes(
    scoring_setup,
):
    import uvicorn
    from rag_eval.store import EvalControlClient
    from rag_eval.worker import ScoringWorker

    owner = scoring_setup["owner"]
    before = await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,))
    quiz_before = await fetch_one(
        "SELECT COUNT(*) AS n FROM quiz_sessions WHERE user_id=%s", (owner,)
    )
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind(("127.0.0.1", 0))
    port = server_socket.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(scoring_setup["app"], log_level="critical", lifespan="off")
    )
    serving = asyncio.create_task(server.serve(sockets=[server_socket]))

    class RunClient(EvalControlClient):
        def claim(self):
            return self._post(
                "/claim",
                {
                    "worker_id": self.worker_id,
                    "lease_seconds": self.lease_seconds,
                    "run_id": scoring_setup["run_id"],
                },
                retry=False,
            )

    control = RunClient(
        f"http://127.0.0.1:{port}/api/v1",
        scoring_setup["settings"].eval_worker_token,
        "http-integration",
    )
    try:
        for _ in range(200):
            if server.started:
                break
            await asyncio.sleep(0.01)
        assert server.started
        state = await asyncio.to_thread(ScoringWorker(control).run_once)
        assert state["state"] == "completed", state
        row = await fetch_one(
            "SELECT status,metrics_json FROM eval_results WHERE result_id=%s",
            (scoring_setup["result_id"],),
        )
        assert row["status"] == "completed"
        metrics = load(row["metrics_json"])
        assert metrics["authorization_safety"]["value"] == 1
        assert metrics["production_isolation"]["value"] == 1
        assert metrics["total_cost_cny"]["value"] == 0
        assert before == await fetch_one(
            "SELECT total_xp FROM users WHERE id=%s", (owner,)
        )
        assert quiz_before == await fetch_one(
            "SELECT COUNT(*) AS n FROM quiz_sessions WHERE user_id=%s", (owner,)
        )
    finally:
        control.close()
        server.should_exit = True
        await asyncio.wait_for(serving, timeout=5)
        server_socket.close()


@pytest.mark.asyncio
async def test_expired_artifact_run_cannot_be_claimed_for_scoring(scoring_setup):
    await execute(
        "UPDATE eval_runs SET manifest_json=JSON_SET(manifest_json,'$.raw_artifacts_status','expired') WHERE run_id=%s",
        (scoring_setup["run_id"],),
    )
    response = await scoring_setup["api"].post(
        PREFIX + "/claim",
        json={"worker_id": "expired-check", "run_id": scoring_setup["run_id"]},
    )
    assert response.status_code == 204
    row = await fetch_one(
        "SELECT error_code FROM eval_results WHERE result_id=%s",
        (scoring_setup["result_id"],),
    )
    assert row["error_code"] == "raw_artifacts_expired"
