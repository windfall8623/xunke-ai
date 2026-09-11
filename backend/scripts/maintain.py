"""Preview or apply retention after stopping the single RAG owner worker."""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args):
    from app.core.db import close_mysql_pool, init_pool
    from app.services.maintenance import hold_evaluation_run, run_maintenance

    await init_pool()
    try:
        if args.hold_run:
            if not all((args.operator, args.reason, args.basis, args.authorization)):
                raise ValueError(
                    "--hold-run requires --operator, --reason, --basis and --authorization"
                )
            receipt = args.authorization.resolve(strict=True)
            if (
                not receipt.is_file()
                or not 0 < receipt.stat().st_size <= 10 * 1024 * 1024
            ):
                raise ValueError(
                    "Authorization receipt must be a nonempty file of at most 10 MB"
                )
            return await hold_evaluation_run(
                run_id=args.hold_run,
                operator=args.operator,
                reason=args.reason,
                basis=args.basis,
                authorization_sha256=hashlib.sha256(receipt.read_bytes()).hexdigest(),
                apply=args.apply,
            )
        return await run_maintenance(
            apply=args.apply, operator=args.operator, owner_id=args.owner_id
        )
    finally:
        await close_mysql_pool()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions or a retention hold; default is read-only preview",
    )
    parser.add_argument(
        "--operator", help="Local operator identifier, required with --apply"
    )
    parser.add_argument(
        "--owner-id",
        type=int,
        help="Scope SQL retention and candidate cleanup to one owner; skip unattributed orphan files",
    )
    parser.add_argument(
        "--hold-run",
        help="Record long retention for one completed public/self-authored release run",
    )
    parser.add_argument(
        "--reason", help="Retention purpose, without private source text"
    )
    parser.add_argument("--basis", choices=("public_release", "self_authored_release"))
    parser.add_argument(
        "--authorization",
        type=Path,
        help="Operator-verified authorization receipt; only SHA-256 is stored",
    )
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args))
    except Exception as exc:
        from app.core.errors import AppError

        parser.exit(
            1,
            (
                f"{exc.code}: {exc.message}"
                if isinstance(exc, AppError)
                else type(exc).__name__
            )
            + "\n",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("errors"):
        parser.exit(1)


if __name__ == "__main__":
    main()
