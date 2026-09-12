"""Qdrant-backed artifact access without opening embedded Chroma in readers."""

from __future__ import annotations

import asyncio
import json
import os

from app.rag.artifact_store import ArtifactStore, OwnerIndexStore
from app.rag.errors import OwnerRequired
from app.rag.index_artifacts import build_index_artifacts, read_manifest


def qdrant_projection(settings, *, writable):
    from app.rag.providers.qdrant_projection import QdrantProjectionStore

    if not settings.qdrant_read_only_api_key or (writable and not settings.qdrant_api_key):
        raise ValueError("Qdrant requires an explicit key for each worker role")
    return QdrantProjectionStore(
        settings.qdrant_url,
        api_key=settings.qdrant_api_key if writable else "",
        read_only_api_key=settings.qdrant_read_only_api_key,
        writable=writable,
        search_timeout_seconds=settings.qdrant_search_timeout_seconds,
        write_timeout_seconds=settings.qdrant_write_timeout_seconds,
        rpc_concurrency=settings.qdrant_rpc_concurrency,
        batch_size=settings.qdrant_batch_size,
        max_request_bytes=settings.qdrant_max_request_bytes,
        vector_on_disk=settings.qdrant_vector_on_disk,
        hnsw_m=settings.qdrant_hnsw_m,
        hnsw_ef_construct=settings.qdrant_hnsw_ef_construct,
        hnsw_ef_search=settings.qdrant_hnsw_ef_search,
    )


class RemoteIndexStore(ArtifactStore):
    def __init__(self, root, *, settings, writable=False):
        super().__init__(root)
        self.backend = "qdrant"
        self.target_revision = settings.vector_target_revision
        self.collection_prefix = settings.qdrant_collection_prefix
        self.registry_enabled = True
        self.writable = writable
        self._pid, self._closed = os.getpid(), False
        self._build_lock = asyncio.Lock()
        self._lock_handle = None
        if writable:
            self._lock_handle = self.resolve_key(".rag-writer.lock").open("a+b")
            try:
                if os.name == "nt":
                    import msvcrt
                    if self._lock_handle.seek(0, 2) == 0:
                        self._lock_handle.write(b"0")
                        self._lock_handle.flush()
                    self._lock_handle.seek(0)
                    msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                self._lock_handle.close()
                raise OwnerRequired("The Qdrant index writer is already running") from exc
        try:
            self.projection = qdrant_projection(settings, writable=writable)
        except BaseException:
            self.close()
            raise

    def _check_owner(self):
        if self._closed or self._pid != os.getpid():
            raise OwnerRequired("Artifact runtime is closed or belongs to another process")

    def _check_writer(self):
        self._check_owner()
        if not self.writable:
            raise OwnerRequired("Generation workers cannot build or delete vector projections")

    async def build(self, request, embedding, budget=None):
        self._check_writer()
        async with self._build_lock:
            return await build_index_artifacts(self, self.projection, request, embedding, budget)

    def read_build(self, manifest):
        self._check_owner()
        return read_manifest(self, manifest)

    async def search(self, request):
        from app.services.vector_projection_service import require_ready

        self._check_owner()
        ref = await require_ready(request.ref, backend=self.backend, target_revision=self.target_revision)
        return await self.projection.search(request.model_copy(update={"ref": ref}))

    def read_docstore(self, manifest):
        from llama_index.core.storage.docstore import SimpleDocumentStore

        built = self.read_build(manifest)
        return SimpleDocumentStore.from_dict(json.loads(
            self.resolve_key(built.projection_key + "/docstore.json").read_bytes()
        )).docs

    def attempts_for_document(self, *, owner_id, namespace, doc_id):
        # This implementation only scans application artifacts and uses no Chroma API.
        return OwnerIndexStore.attempts_for_document(
            self, owner_id=owner_id, namespace=namespace, doc_id=doc_id
        )

    async def purge_document(self, *, owner_id, namespace, doc_id):
        from app.rag.projection_cleanup import purge_registered_document

        self._check_writer()
        return await purge_registered_document(
            self, owner_id=owner_id, namespace=namespace, doc_id=doc_id,
        )

    async def aclose(self):
        try:
            await self.projection.close()
        finally:
            self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._lock_handle is not None and not self._lock_handle.closed:
            if os.name == "nt":
                import msvcrt
                self._lock_handle.seek(0)
                msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
            self._lock_handle.close()
