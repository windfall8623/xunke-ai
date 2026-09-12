"""Remove every registered backend before discarding shared source archives."""

from __future__ import annotations

import shutil

from app.core.values import load
from app.rag.blocking_io import run_file_io
from app.rag.errors import SourceUnavailable
from app.rag.vector_store import ProjectionRef


async def purge_registered_document(store, *, owner_id, namespace, doc_id):
    from app.services import vector_projection_service as registry

    await registry.assert_document_drained(owner_id, doc_id)
    projections = await registry.document_projections(owner_id, doc_id, include_deleted=True)
    intents = store.attempts_for_document(owner_id=owner_id, namespace=namespace, doc_id=doc_id)
    registered = {r["projection_key"] for r in projections}
    if any(intent["projection_key"] not in registered for intent in intents):
        raise SourceUnavailable("Unregistered legacy attempts require projection backfill")

    opened_chroma = opened_qdrant = None
    try:
        for row in projections:
            ref = ProjectionRef.model_validate(load(row["ref_json"]))
            if (ref.owner_id, ref.namespace, ref.doc_id) != (owner_id, namespace, doc_id):
                raise SourceUnavailable("Cleanup projection does not match document ownership")
            if row["status"] == "deleted":
                # A prior run can have confirmed remote deletion and then crashed
                # before unlinking files. The SQL receipt makes this retry safe.
                continue
            await registry.mark_deleting(ref)
            if ref.backend == getattr(store, "backend", "chroma"):
                projection = store.projection
            elif ref.backend == "chroma":
                if opened_chroma is None:
                    from app.rag.artifact_store import OwnerIndexStore
                    opened_chroma = await run_file_io(
                        lambda: OwnerIndexStore(store.root, process_role="rag_owner")
                    )
                projection = opened_chroma.projection
            else:
                if opened_qdrant is None:
                    from app.core.config import get_settings
                    from app.rag.remote_index_store import qdrant_projection
                    opened_qdrant = qdrant_projection(get_settings(), writable=True)
                projection = opened_qdrant
            receipt = await registry.recorded_call(
                ref, "delete", lambda p=projection, r=ref: p.delete_attempt(r)
            )
            if receipt.remaining_visible != 0:
                raise SourceUnavailable("Projection deletion was not verified empty")
            await registry.mark_deleted(ref)
    finally:
        if opened_chroma is not None:
            await run_file_io(opened_chroma.close)
        if opened_qdrant is not None:
            await opened_qdrant.close()

    for key in sorted(registered):
        path, root = store.resolve_key(key), store.resolve_key("rag/projections")
        if path == root or not path.is_relative_to(root):
            raise SourceUnavailable("Cleanup path escaped projection storage")
        if path.exists():
            await run_file_io(shutil.rmtree, path)
    return store.attempts_for_document(owner_id=owner_id, namespace=namespace, doc_id=doc_id)
