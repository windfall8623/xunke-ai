"""Zero-provider projection dispatch and terminal bookkeeping."""

from app.core.db import execute, fetch_one
from app.core.values import dump
from app.services.learning_projection_service import project_activity


async def run_learning_projection(job) -> None:
    await project_activity(job)


async def reconcile_learning_projection(conn, job) -> None:
    """Keep failed delivery discoverable without acknowledging its outbox row.

    The owner already holds this terminal job lock. A later repaired delivery
    can consume the same immutable event; only project_activity may acknowledge
    it or publish learning state under a valid lease.
    """
    if job["kind"] != "learning_project" or job["status"] not in {
        "failed",
        "cancelled",
    }:
        return
    event = await fetch_one(
        "SELECT event_id,processed_at FROM learning_outbox WHERE task_id=%s AND owner_id=%s",
        (job["task_id"], job["user_id"]),
        conn=conn,
    )
    if event is not None and event["processed_at"] is None:
        await execute(
            "UPDATE quiz_tasks SET result_json=%s WHERE task_id=%s AND user_id=%s "
            "AND status IN ('failed','cancelled')",
            (
                dump({"event_id": event["event_id"], "status": "unprocessed"}),
                job["task_id"],
                job["user_id"],
            ),
            conn=conn,
        )
