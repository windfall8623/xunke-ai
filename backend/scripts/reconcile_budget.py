"""List unknown charges, or explicitly reconcile one with an operator's bill receipt."""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args):
    from app.core.db import close_mysql_pool, init_pool
    from app.services.reconciliation_service import reconcile_charge, unresolved_charges

    await init_pool()
    try:
        if not args.apply:
            return {"mode": "read_only", "unresolved": await unresolved_charges()}
        if not all(
            (
                args.call_id,
                args.actual_cny is not None,
                args.receipt,
                args.reference,
                args.operator,
            )
        ):
            raise ValueError(
                "--apply requires --call-id, --actual-cny, --receipt, --reference and --operator"
            )
        receipt = args.receipt.resolve(strict=True)
        if not receipt.is_file() or not 0 < receipt.stat().st_size <= 10 * 1024 * 1024:
            raise ValueError("Receipt must be a nonempty file of at most 10 MB")
        checksum = hashlib.sha256(receipt.read_bytes()).hexdigest()
        return await reconcile_charge(
            args.call_id,
            actual_cny=args.actual_cny,
            evidence_sha256=checksum,
            receipt_reference=args.reference,
            operator=args.operator,
        )
    finally:
        await close_mysql_pool()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Settle one inactive charge; default only lists unresolved reservations",
    )
    parser.add_argument("--call-id")
    parser.add_argument("--actual-cny")
    parser.add_argument(
        "--receipt",
        type=Path,
        help="Private operator-verified bill file; only SHA-256 is stored",
    )
    parser.add_argument(
        "--reference", help="Invoice and line identifier; do not include secrets"
    )
    parser.add_argument("--operator")
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


if __name__ == "__main__":
    main()
