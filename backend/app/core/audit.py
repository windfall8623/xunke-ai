"""Read-only migration audit. Never infer ownership or award historical XP."""

from app.core.db import fetch_all, fetch_one


async def ownership_violations(*, conn=None):
    failures = {}
    for table in ("answer_records", "reports"):
        row = await fetch_one(
            f"SELECT COUNT(*) AS n FROM {table} r JOIN quiz_sessions q ON q.quiz_id=r.quiz_id WHERE r.user_id IS NOT NULL AND NOT (r.user_id <=> q.user_id)",
            conn=conn,
        )
        failures[table] = row["n"]
    return failures


async def audit_database():
    users = await fetch_all("SELECT id,total_xp FROM users ORDER BY id")
    counts = {}
    for table in (
        "quiz_sessions",
        "answer_records",
        "reports",
        "kb_documents",
        "quiz_tasks",
    ):
        counts[table] = (await fetch_one(f"SELECT COUNT(*) AS n FROM {table}"))["n"]
    from app.core.values import digest, dump

    counts["user_count"] = len(users)
    counts["user_ids_and_xp_sha256"] = digest(dump(users))
    counts["xp_total"] = sum(user["total_xp"] for user in users)
    counts["ownership_violations"] = await ownership_violations()
    return counts
