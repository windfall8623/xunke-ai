"""Offline vector migration. Never changes service configuration or regenerates embeddings."""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def run(args):
    from app.core.config import get_settings
    from app.core.db import close_mysql_pool, init_pool
    from app.rag.artifact_store import ArtifactStore, OwnerIndexStore
    from app.rag.index_artifacts import run_file_io
    from app.rag.remote_index_store import RemoteIndexStore
    from app.services import vector_migration_service as migration

    settings = get_settings()
    store = ArtifactStore(settings.data_dir)
    remote = chroma = None
    await init_pool()
    try:
        recovery_path = getattr(args, "recovery_proof", None)
        if recovery_path is not None and args.command not in {"copy", "restore-chroma"}:
            raise ValueError("Recovery proof is only accepted for copy or restore-chroma")
        proof = await run_file_io(lambda: json.loads(Path(recovery_path).read_text(encoding="utf-8"))) if recovery_path else None
        chosen = settings.model_copy(update={"vector_target_revision": args.target_revision})
        if args.command == "plan":
            return await migration.plan(store, revision=args.target_revision, prefix=settings.qdrant_collection_prefix)
        if args.command in {"switch-check", "rollback-check"}:
            backend = "chroma" if args.command == "rollback-check" else "qdrant"
            revision = "legacy-v1" if backend == "chroma" else args.target_revision
            preliminary = await migration.switch_check(store, backend=backend, revision=revision)
            if preliminary["status"] == "blocked":
                return preliminary
            if backend == "qdrant":
                remote = RemoteIndexStore(store.root, settings=chosen, writable=False)
                projection = remote.projection
            elif preliminary["projection_count"]:
                chroma = await run_file_io(lambda: OwnerIndexStore(store.root, process_role="rag_owner"))
                projection = chroma.projection
            else:
                return preliminary
            return await migration.switch_check(store, backend=backend, revision=revision, projection=projection)
        if args.command == "verify":
            remote = RemoteIndexStore(store.root, settings=chosen, writable=False)
            return await migration.verify(store, remote.projection, backend="qdrant", revision=args.target_revision, prefix=settings.qdrant_collection_prefix)
        if args.command == "copy" or proof is not None:
            remote = RemoteIndexStore(store.root, settings=chosen, writable=args.command == "copy")
        async with migration.maintenance(recovery_proof=proof, projection=remote.projection if remote else None):
            chroma = await run_file_io(lambda: OwnerIndexStore(store.root, process_role="rag_owner"))
            try:
                if args.command == "copy":
                    return await migration.copy(chroma, remote, run_id=args.run_id)
                return await migration.restore_chroma(chroma, qdrant_revision=args.target_revision, run_id=args.run_id)
            finally:
                await run_file_io(chroma.close)
                chroma = None
    finally:
        if remote is not None:
            await remote.aclose()
        if chroma is not None:
            await run_file_io(chroma.close)
        await close_mysql_pool()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "copy", "verify", "switch-check", "restore-chroma", "rollback-check"])
    parser.add_argument("--target-revision", default="qdrant-v1")
    parser.add_argument("--run-id", default="initial-qdrant-v1")
    parser.add_argument("--recovery-proof", type=Path, help="Explicit worker exit evidence; unknown Qdrant operations also require a later actual server restart")
    args = parser.parse_args()
    if not all(re.fullmatch(r"[a-zA-Z0-9_.-]{1,64}", x) for x in (args.target_revision, args.run_id)):
        parser.error("Revisions and run IDs must be short identifiers")
    try:
        report = asyncio.run(run(args))
    except Exception as exc:
        # Provider exceptions can contain URLs or credentials. Keep CLI failures redacted.
        from app.rag.errors import RagError
        error = {"status": "failed", "error_type": type(exc).__name__}
        if isinstance(exc, RagError):
            error.update(error_code=exc.code, message=exc.message)
        print(json.dumps(error))
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 1 if report.get("status") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
