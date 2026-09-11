"""Explicit expand/backfill/constraint migration with resumable DDL checkpoints."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args):
    from app.core.audit import audit_database
    from app.core.db import close_mysql_pool, init_mysql, init_pool
    from app.core.migrations import migrate, migration_status

    try:
        if args.init_database:
            await init_mysql()
        else:
            await init_pool()
            if not args.status:
                await migrate()
        report = {
            "migrations": await migration_status(),
            "audit": await audit_database(),
        }
        encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        if args.audit_output:
            Path(args.audit_output).write_text(encoded, encoding="utf-8")
        print(encoded)
    finally:
        await close_mysql_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument(
        "--init-database",
        action="store_true",
        help="Development only: create the configured empty database if missing",
    )
    parser.add_argument("--audit-output")
    asyncio.run(run(parser.parse_args()))
