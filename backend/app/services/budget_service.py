"""Atomic resource reservations. Unknown calls retain their reservation for reconciliation."""

from decimal import Decimal

from app.core.db import execute, fetch_one, transaction
from app.core.errors import AppError, conflict
from app.core.values import dump, load


async def reserve_budget(operation_id, resource_type, amount, accounts, *, conn=None):
    if conn is None:
        async with transaction() as tx:
            return await reserve_budget(
                operation_id, resource_type, amount, accounts, conn=tx
            )
    amount = Decimal(str(amount))
    if amount <= 0 or not accounts or len(set(k for k, _ in accounts)) != len(accounts):
        raise ValueError("Positive amount and distinct accounts required")
    ordered = sorted(accounts)
    for key, quota in ordered:
        await execute(
            "INSERT INTO budget_accounts(account_key,resource_type,quota) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE account_key=account_key",
            (key, resource_type, quota),
            conn=conn,
        )
        await fetch_one(
            "SELECT account_key FROM budget_accounts WHERE account_key=%s FOR UPDATE",
            (key,),
            conn=conn,
        )
    old = await fetch_one(
        "SELECT * FROM budget_reservations WHERE operation_id=%s AND resource_type=%s FOR UPDATE",
        (operation_id, resource_type),
        conn=conn,
    )
    if old:
        if old["reserved"] != amount or load(old["accounts_json"]) != [
            k for k, _ in ordered
        ]:
            raise conflict("reservation_conflict", "预算预留参数不一致")
        return old
    for key, _ in ordered:
        row = await fetch_one(
            "SELECT quota,used,reserved FROM budget_accounts WHERE account_key=%s",
            (key,),
            conn=conn,
        )
        if row["used"] + row["reserved"] + amount > row["quota"]:
            raise AppError(429, "budget_exceeded", "本次操作超过可用额度")
    for key, _ in ordered:
        await execute(
            "UPDATE budget_accounts SET reserved=reserved+%s,revision=revision+1 WHERE account_key=%s",
            (amount, key),
            conn=conn,
        )
    await execute(
        "INSERT INTO budget_reservations(operation_id,resource_type,accounts_json,reserved) VALUES(%s,%s,%s,%s)",
        (operation_id, resource_type, dump([k for k, _ in ordered]), amount),
        conn=conn,
    )
    return {"operation_id": operation_id, "status": "reserved", "reserved": amount}


async def settle_budget(
    operation_id, resource_type, actual=None, *, unknown=False, conn=None
):
    if conn is None:
        async with transaction() as tx:
            return await settle_budget(
                operation_id, resource_type, actual, unknown=unknown, conn=tx
            )
    preview = await fetch_one(
        "SELECT accounts_json FROM budget_reservations WHERE operation_id=%s AND resource_type=%s",
        (operation_id, resource_type),
        conn=conn,
    )
    if not preview:
        raise ValueError("Reservation missing")
    # Same account ordering as reserve avoids lock inversion across operations.
    accounts = sorted(load(preview["accounts_json"]))
    for key in accounts:
        await fetch_one(
            "SELECT account_key FROM budget_accounts WHERE account_key=%s FOR UPDATE",
            (key,),
            conn=conn,
        )
    row = await fetch_one(
        "SELECT * FROM budget_reservations WHERE operation_id=%s AND resource_type=%s FOR UPDATE",
        (operation_id, resource_type),
        conn=conn,
    )
    if row["status"] in ("settled", "released"):
        return row
    if unknown:
        await execute(
            "UPDATE budget_reservations SET status='unknown' WHERE operation_id=%s AND resource_type=%s",
            (operation_id, resource_type),
            conn=conn,
        )
        return {"status": "unknown"}
    actual = Decimal(str(actual or 0))
    if actual < 0 or actual > row["reserved"]:
        raise ValueError("Actual use must be within the reserved ceiling")
    for key in accounts:
        await execute(
            "UPDATE budget_accounts SET reserved=reserved-%s,used=used+%s,revision=revision+1 WHERE account_key=%s",
            (row["reserved"], actual, key),
            conn=conn,
        )
    status = "settled" if actual else "released"
    await execute(
        "UPDATE budget_reservations SET status=%s,actual=%s WHERE operation_id=%s AND resource_type=%s",
        (status, actual, operation_id, resource_type),
        conn=conn,
    )
    return {"status": status, "actual": actual}
