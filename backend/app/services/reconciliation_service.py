"""Operator-only reconciliation. No API exposes or automatically releases unknown charges."""

import re
from datetime import timedelta
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import dump, load, now
from app.services import budget_service


async def unresolved_charges():
    rows = await fetch_all(
        "SELECT p.call_id,p.stage,p.mode,p.status,p.created_at,b.reserved "
        "FROM provider_calls p JOIN budget_reservations b ON b.operation_id=p.call_id "
        "AND b.resource_type='cny' WHERE b.status IN ('reserved','unknown') "
        "ORDER BY p.created_at LIMIT 200"
    )
    return [
        {
            **row,
            "reserved": str(row["reserved"]),
            "created_at": row["created_at"].isoformat() + "Z",
        }
        for row in rows
    ]


async def reconcile_charge(
    call_id, *, actual_cny, evidence_sha256, receipt_reference, operator
):
    try:
        amount = Decimal(str(actual_cny))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Invalid amount")
        amount = amount.quantize(Decimal(".000001"), rounding=ROUND_CEILING)
    except (InvalidOperation, ValueError) as exc:
        raise AppError(
            422, "invalid_charge", "实际费用必须为有限非负人民币金额"
        ) from exc
    if (
        not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256)
        or not receipt_reference.strip()
        or len(receipt_reference) > 256
        or not operator.strip()
        or len(operator) > 128
    ):
        raise AppError(
            422, "receipt_required", "需要账单凭据 SHA-256、账单行标识和操作人"
        )
    receipt = {
        "actual_cny": str(amount),
        "evidence_sha256": evidence_sha256,
        "receipt_reference": receipt_reference,
        "operator": operator,
    }
    preview = await fetch_one(
        "SELECT operation_id FROM provider_calls WHERE call_id=%s", (call_id,)
    )
    if not preview:
        raise not_found()
    async with transaction() as conn:
        operation = preview["operation_id"]
        if operation.startswith("evalscore:"):
            result_id = operation.split(":")[1]
            result = await fetch_one(
                "SELECT status,scoring_expires_at FROM eval_results WHERE result_id=%s FOR UPDATE",
                (result_id,),
                conn=conn,
            )
            if not result or result["status"] == "scoring":
                raise conflict("call_still_active", "请等待评分任务停止后核对账单")
        else:
            job = await fetch_one(
                "SELECT status FROM quiz_tasks WHERE task_id=%s FOR UPDATE",
                (operation,),
                conn=conn,
            )
            if not job or job["status"] in ("pending", "running"):
                raise conflict("call_still_active", "请等待任务停止后核对账单")
        call = await fetch_one(
            "SELECT * FROM provider_calls WHERE call_id=%s FOR UPDATE",
            (call_id,),
            conn=conn,
        )
        existing = await fetch_one(
            "SELECT * FROM budget_reconciliations WHERE call_id=%s AND resource_type='cny'",
            (call_id,),
            conn=conn,
        )
        if existing:
            if existing["actual_cny"] != amount or any(
                existing[key] != receipt[key]
                for key in ("evidence_sha256", "receipt_reference", "operator")
            ):
                raise conflict("reconciliation_conflict", "此调用已按其他账单凭据结算")
            return {
                "call_id": call_id,
                "status": "settled" if amount else "released",
                **receipt,
            }
        # All supported external I/O is bounded well below this quiet period.
        # A cancelled request can still have a response in flight; never reconcile it immediately.
        if call["created_at"] > now() - timedelta(hours=24):
            raise conflict(
                "call_still_active", "未知调用至少保留 24 小时后再凭账单核对"
            )
        reservation = await fetch_one(
            "SELECT status,reserved FROM budget_reservations WHERE operation_id=%s AND resource_type='cny'",
            (call_id,),
            conn=conn,
        )
        if not reservation or reservation["status"] not in ("reserved", "unknown"):
            raise conflict("charge_already_settled", "此调用没有待核对的费用预留")
        if amount > reservation["reserved"]:
            raise conflict(
                "charge_exceeds_reservation",
                "账单高于预留上限，保留未知状态并人工审计超额原因",
            )
        settled = await budget_service.settle_budget(call_id, "cny", amount, conn=conn)
        await execute(
            "INSERT INTO budget_reconciliations(call_id,resource_type,actual_cny,evidence_sha256,receipt_reference,operator) "
            "VALUES(%s,'cny',%s,%s,%s,%s)",
            (call_id, amount, evidence_sha256, receipt_reference, operator),
            conn=conn,
        )
        usage = load(call["usage_json"], {})
        usage.update(
            cost_cny=float(amount),
            cost_status="provider_reported",
            reconciliation={**receipt, "reconciled_at": now().isoformat() + "Z"},
        )
        await execute(
            "UPDATE provider_calls SET usage_json=%s WHERE call_id=%s",
            (dump(usage), call_id),
            conn=conn,
        )
        return {"call_id": call_id, "status": settled["status"], **receipt}
