"""Explicit local role administration; no public role-escalation endpoint."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args):
    from app.core.db import close_mysql_pool, execute, fetch_one, init_pool, transaction

    await init_pool()
    try:
        async with transaction() as conn:
            user = await fetch_one(
                "SELECT id,role FROM users WHERE id=%s FOR UPDATE",
                (args.user_id,),
                conn=conn,
            )
            if not user:
                raise SystemExit("User does not exist")
            await execute(
                "UPDATE users SET role=%s WHERE id=%s",
                (args.role, args.user_id),
                conn=conn,
            )
            print(
                f"user_id={args.user_id} role={args.role} previous_role={user['role']}"
            )
    finally:
        await close_mysql_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--role", choices=["learner", "evaluator"], required=True)
    asyncio.run(run(parser.parse_args()))
