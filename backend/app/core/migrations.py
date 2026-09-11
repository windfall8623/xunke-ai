"""MySQL DDL auto-commits: checkpoint each guarded statement, verify checksums."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from app.core.db import execute, fetch_all, fetch_one, require_pool

MIGRATION_DIR = Path(__file__).resolve().parents[2] / "migrations"


async def _tables(conn):
    exists = await fetch_all(
        "SELECT table_name FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('schema_migrations','schema_migration_steps')",
        conn=conn,
    )
    names = {next(iter(r.values())) for r in exists}
    if "schema_migrations" not in names:
        await execute(
            "CREATE TABLE schema_migrations (version VARCHAR(80) PRIMARY KEY, checksum CHAR(64) NOT NULL, applied_at DATETIME(6) NULL)",
            conn=conn,
        )
    if "schema_migration_steps" not in names:
        await execute(
            "CREATE TABLE schema_migration_steps (version VARCHAR(80) NOT NULL, step INT NOT NULL, checksum CHAR(64) NOT NULL, PRIMARY KEY(version,step))",
            conn=conn,
        )


async def migration_status():
    rows = await fetch_all("SELECT version,checksum,applied_at FROM schema_migrations")
    existing = {r["version"]: r for r in rows}
    return [
        {
            "version": p.stem,
            "applied": p.stem in existing
            and existing[p.stem]["applied_at"] is not None,
            "checksum_matches": p.stem not in existing
            or existing[p.stem]["checksum"]
            == hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in sorted(MIGRATION_DIR.glob("*.sql"))
    ]


async def migrate(target_version=None):
    async with require_pool().acquire() as conn:
        lock = await fetch_one(
            "SELECT GET_LOCK('zhixue_schema_migrate',30) AS acquired", conn=conn
        )
        if lock["acquired"] != 1:
            raise RuntimeError("Another migration is running")
        try:
            await _tables(conn)
            for path in sorted(MIGRATION_DIR.glob("*.sql")):
                if target_version and path.stem > target_version:
                    break
                checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                old = await fetch_one(
                    "SELECT * FROM schema_migrations WHERE version=%s",
                    (path.stem,),
                    conn=conn,
                )
                if old and old["checksum"] != checksum:
                    raise RuntimeError(f"Migration checksum changed: {path.name}")
                if old and old["applied_at"]:
                    continue
                if path.stem == "006_history_ownership":
                    from app.core.audit import ownership_violations

                    violations = await ownership_violations(conn=conn)
                    if any(violations.values()):
                        raise RuntimeError(
                            "Historical ownership audit failed; repair from verified records before migration: "
                            + str(violations)
                        )
                if path.stem == "009_password_identity_unique":
                    duplicates = await fetch_all(
                        "SELECT user_id,COUNT(*) AS identity_count FROM auth_identities "
                        "WHERE provider='password' GROUP BY user_id HAVING COUNT(*)>1 "
                        "ORDER BY user_id LIMIT 20",
                        conn=conn,
                    )
                    if duplicates:
                        # Report only owner/count metadata, never login subjects
                        # or credential hashes. Existing identities stay intact.
                        raise RuntimeError(
                            "Duplicate password identities require manual resolution "
                            "before migration 009 (no identities were changed): "
                            + str(duplicates)
                        )
                await execute(
                    "INSERT IGNORE INTO schema_migrations(version,checksum) VALUES(%s,%s)",
                    (path.stem, checksum),
                    conn=conn,
                )
                for step, statement in enumerate(
                    path.read_text(encoding="utf-8").split(";")
                ):
                    statement = statement.strip()
                    if not statement:
                        continue
                    done = await fetch_one(
                        "SELECT checksum FROM schema_migration_steps WHERE version=%s AND step=%s",
                        (path.stem, step),
                        conn=conn,
                    )
                    if done:
                        continue
                    guard = re.search(r"-- @(column|index) (\w+) (\w+)", statement)
                    skip = False
                    if guard:
                        kind, table, name = guard.groups()
                        if kind == "column":
                            skip = await fetch_one(
                                "SELECT 1 FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name=%s AND column_name=%s",
                                (table, name),
                                conn=conn,
                            )
                        else:
                            skip = await fetch_one(
                                "SELECT 1 FROM information_schema.table_constraints WHERE constraint_schema=DATABASE() AND table_name=%s AND constraint_name=%s",
                                (table, name),
                                conn=conn,
                            )
                    if not skip:
                        await execute(statement, conn=conn)
                    await execute(
                        "INSERT INTO schema_migration_steps(version,step,checksum) VALUES(%s,%s,%s)",
                        (
                            path.stem,
                            step,
                            hashlib.sha256(statement.encode()).hexdigest(),
                        ),
                        conn=conn,
                    )
                await execute(
                    "UPDATE schema_migrations SET applied_at=UTC_TIMESTAMP(6) WHERE version=%s",
                    (path.stem,),
                    conn=conn,
                )
        finally:
            await execute("SELECT RELEASE_LOCK('zhixue_schema_migrate')", conn=conn)
