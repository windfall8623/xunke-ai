"""Unknown provider charges require an explicit, immutable operator receipt."""

import asyncio

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def unknown_charge(learner):
    from app.core.db import execute
    from app.core.values import dump, uid
    from app.services import budget_service, job_service

    _, session = learner
    owner = session["user"]["id"]
    job = await job_service.enqueue_job(
        owner, "quiz", {"user_input": "synthetic"}, "reconcile-test"
    )
    call_id = uid("call")
    account = "reconcile:" + call_id
    await budget_service.reserve_budget(call_id, "cny", 1, [(account, 10)])
    await budget_service.settle_budget(call_id, "cny", unknown=True)
    await execute(
        "INSERT INTO provider_calls(call_id,operation_id,owner_id,mode,stage,status,usage_json,created_at) VALUES(%s,%s,%s,'production','llm','unknown',%s,UTC_TIMESTAMP(6)-INTERVAL 2 DAY)",
        (
            call_id,
            job["task_id"],
            owner,
            dump({"cost_status": "unknown", "cost_cny": None}),
        ),
    )
    await execute(
        "UPDATE quiz_tasks SET status='failed' WHERE task_id=%s", (job["task_id"],)
    )
    return call_id, account, job


@pytest.mark.asyncio
async def test_reconciliation_receipt_is_atomic_idempotent_and_immutable(
    unknown_charge,
):
    from app.core.db import fetch_one
    from app.core.errors import AppError
    from app.services.reconciliation_service import reconcile_charge

    call_id, account, _ = unknown_charge
    receipt = dict(
        actual_cny="0.4",
        evidence_sha256="a" * 64,
        receipt_reference="synthetic-bill-line-7",
        operator="test-operator",
    )
    first, retry = await asyncio.gather(
        *(reconcile_charge(call_id, **receipt) for _ in range(2))
    )
    assert first == retry and first["status"] == "settled"
    ledger = await fetch_one(
        "SELECT used,reserved FROM budget_accounts WHERE account_key=%s", (account,)
    )
    assert float(ledger["used"]) == 0.4 and ledger["reserved"] == 0
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM budget_reconciliations WHERE call_id=%s",
            (call_id,),
        )
    )["n"] == 1
    with pytest.raises(AppError) as conflict:
        await reconcile_charge(call_id, **{**receipt, "actual_cny": "0.5"})
    assert conflict.value.code == "reconciliation_conflict"


@pytest.mark.asyncio
async def test_reconciliation_rejects_active_jobs_and_unproved_cost(unknown_charge):
    from app.core.db import execute, fetch_one
    from app.core.errors import AppError
    from app.services.reconciliation_service import reconcile_charge

    call_id, account, job = unknown_charge
    receipt = dict(
        actual_cny="0",
        evidence_sha256="a" * 64,
        receipt_reference="synthetic-no-charge",
        operator="test-operator",
    )
    await execute(
        "UPDATE quiz_tasks SET status='running' WHERE task_id=%s", (job["task_id"],)
    )
    with pytest.raises(AppError) as active:
        await reconcile_charge(call_id, **receipt)
    assert active.value.code == "call_still_active"
    await execute(
        "UPDATE quiz_tasks SET status='failed' WHERE task_id=%s", (job["task_id"],)
    )
    with pytest.raises(AppError):
        await reconcile_charge(call_id, **{**receipt, "evidence_sha256": ""})
    with pytest.raises(AppError) as over:
        await reconcile_charge(call_id, **{**receipt, "actual_cny": "2"})
    assert over.value.code == "charge_exceeds_reservation"
    ledger = await fetch_one(
        "SELECT used,reserved FROM budget_accounts WHERE account_key=%s", (account,)
    )
    assert ledger["used"] == 0 and ledger["reserved"] == 1
