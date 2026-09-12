"""Immutable canonical files and attempt-isolated, single-owner Chroma projection.

SQL remains authoritative for ready/active pointers and authorization. A stored
candidate is not discoverable without its exact manifest in an authorized scope.
Deletion callers must fence/wait for in-flight jobs, then sweep again until empty.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import threading
import uuid
from pathlib import Path

from app.rag.contracts import (
    BuildRequest,
    BuildResult,
    CanonicalDocument,
    SourceManifest,
    stable_hash,
)
from app.rag.errors import OwnerRequired, SourceUnavailable


def projection_key(
    owner_id: int,
    namespace: str,
    doc_id: str,
    version_id: str,
    parse_id: str,
    build_id: str,
    attempt_id: str,
) -> str:
    return "rag/projections/" + stable_hash(
        [owner_id, namespace, doc_id, version_id, parse_id, build_id, attempt_id]
    )


class ArtifactStore:
    """Filesystem-only API; safe for API/source readers after SQL authorization."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve_key(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if path == self.root or not path.is_relative_to(self.root):
            raise SourceUnavailable("Artifact storage key is invalid")
        return path

    def put_json(self, key: str, payload: dict, *, immutable: bool = True) -> str:
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return self.put_bytes(key, encoded, immutable=immutable)

    def put_bytes(self, key: str, encoded: bytes, *, immutable: bool = True) -> str:
        path = self.resolve_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and immutable:
            if path.read_bytes() != encoded:
                raise SourceUnavailable(
                    "Immutable artifact key already has different content"
                )
            return key
        # A short temporary basename also works on Windows without LongPathsEnabled.
        temporary = path.with_name("." + uuid.uuid4().hex[:12] + ".tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return key

    def load_canonical(self, key: str) -> CanonicalDocument:
        try:
            return CanonicalDocument.model_validate_json(
                self.resolve_key(key).read_bytes()
            )
        except SourceUnavailable:
            raise
        except Exception as exc:
            raise SourceUnavailable("Canonical source artifact is unavailable") from exc

    def save_canonical(
        self, document: CanonicalDocument, key: str | None = None
    ) -> str:
        key = key or (
            "sources/"
            + stable_hash(
                [
                    document.owner_id,
                    document.namespace,
                    document.doc_id,
                    document.document_version_id,
                ]
            )[:32]
            + "/"
            + document.parse_artifact_id
            + ".json"
        )
        return self.put_json(key, document.model_dump(mode="json"))

    def save_web_snapshot(self, snapshot: dict) -> str:
        key = (
            "snapshots/"
            + stable_hash([snapshot["owner_id"], snapshot["namespace"]])[:24]
            + "/"
            + snapshot["snapshot_id"]
            + ".json"
        )
        return self.put_json(key, snapshot)

    def load_web_snapshot(self, key: str) -> dict:
        from app.rag.contracts import text_hash

        try:
            snapshot = json.loads(self.resolve_key(key).read_bytes())
            if text_hash(snapshot["text"]) != snapshot["snapshot_hash"]:
                raise SourceUnavailable("Web snapshot checksum mismatch")
            return snapshot
        except SourceUnavailable:
            raise
        except Exception as exc:
            raise SourceUnavailable("Web source snapshot is unavailable") from exc


class OwnerIndexStore(ArtifactStore):
    def __init__(self, root: str | Path, *, process_role: str):
        if process_role != "rag_owner":
            raise OwnerRequired("Only the RAG owner worker may open Chroma")
        super().__init__(root)
        self._pid = os.getpid()
        self._closed = False
        self._build_lock = asyncio.Lock()
        self._io_lock = threading.RLock()
        self._lock_handle = (self.root / ".rag-owner.lock").open("a+b")
        try:
            self._lock_handle.seek(0)
            if os.name == "nt":
                import msvcrt

                # Lock a persistent byte; Windows releases this lock on process death.
                if (self.root / ".rag-owner.lock").stat().st_size == 0:
                    self._lock_handle.write(b"0")
                    self._lock_handle.flush()
                self._lock_handle.seek(0)
                msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._lock_handle.close()
            raise OwnerRequired(
                "Persistent RAG directory already has an owner"
            ) from exc
        try:
            import chromadb
            from chromadb.config import Settings

            # Upstream adapter logs excerpts at DEBUG; suppress that private text path.
            logging.getLogger("llama_index.vector_stores.chroma.base").setLevel(
                logging.WARNING
            )
            self._client = chromadb.PersistentClient(
                path=str(self.root / "chroma"),
                settings=Settings(anonymized_telemetry=False),
            )
        except Exception:
            self._unlock()
            raise
        from app.rag.providers.chroma_projection import ChromaProjectionStore

        self.projection = ChromaProjectionStore(
            self._client, io_lock=self._io_lock
        )

    def _check_owner(self):
        if self._closed or self._pid != os.getpid():
            raise OwnerRequired("RAG store is closed or belongs to another process")

    def _unlock(self):
        if self._lock_handle.closed:
            return
        self._lock_handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._lock_handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
        self._lock_handle.close()

    def close(self):
        if not self._closed:
            self._check_owner()
            self._client.close()
            self._closed = True
            self._unlock()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @staticmethod
    def _key(manifest) -> str:
        return projection_key(
            manifest.owner_id,
            manifest.namespace,
            manifest.doc_id,
            manifest.document_version_id,
            manifest.parse_artifact_id,
            manifest.index_build_id,
            manifest.attempt_id,
        )

    async def build(self, request: BuildRequest, embedding, budget=None) -> BuildResult:
        """Return an unpublished candidate; caller performs SQL lease/CAS publication."""
        self._check_owner()
        from app.rag import index_artifacts

        async with self._build_lock:
            return await index_artifacts.build_index_artifacts(
                self, self.projection, request, embedding, budget
            )

    def read_build(self, manifest: SourceManifest) -> BuildResult:
        """查询热路径：身份与校验和检查；全量核验只属于构建/重放/修复。"""
        from app.rag import index_artifacts

        self._check_owner()
        return index_artifacts.read_manifest(self, manifest)

    def search(self, request) -> list:
        """向量检索经投影层执行；过滤器在 top-k 之前生效。"""
        self._check_owner()
        return self.projection.search(request)

    def read_docstore(self, manifest: SourceManifest):
        from llama_index.core.storage.docstore import SimpleDocumentStore

        result = self.read_build(manifest)
        return SimpleDocumentStore.from_dict(
            json.loads(
                self.resolve_key(result.projection_key + "/docstore.json").read_bytes()
            )
        ).docs

    def delete_attempt(self, manifest) -> None:
        """Delete only this physical attempt, after SQL has fenced its writers."""
        self._check_owner()
        key = self._key(manifest)
        if manifest.projection_key and manifest.projection_key != key:
            raise SourceUnavailable("Invalid cleanup projection key")
        from app.rag.index_artifacts import ref_from_manifest

        ref = ref_from_manifest(manifest)
        self.projection.delete_attempt_sync(ref)
        path = self.resolve_key(key)
        projection_root = self.resolve_key("rag/projections")
        if not path.is_relative_to(projection_root) or path == projection_root:
            raise SourceUnavailable("Cleanup path is outside its attempt")
        if path.exists():
            shutil.rmtree(path)

    def projection_exists(self, manifest) -> bool:
        self._check_owner()
        from app.rag.providers.chroma_projection import collection_name_for

        key = self._key(manifest)
        return self.resolve_key(key).exists() or collection_name_for(key) in {
            c.name for c in self._client.list_collections()
        }

    def attempts_for_document(
        self, *, owner_id: int, namespace: str, doc_id: str
    ) -> list[dict]:
        self._check_owner()
        root = self.resolve_key("rag/projections")
        result = []
        if root.exists():
            for path in root.glob("*/attempt.json"):
                value = json.loads(path.read_bytes())
                if (
                    value.get("owner_id"),
                    value.get("namespace"),
                    value.get("doc_id"),
                ) == (owner_id, namespace, doc_id):
                    result.append(value)
        return result

    def purge_document(
        self, *, owner_id: int, namespace: str, doc_id: str
    ) -> list[dict]:
        if getattr(self, "registry_enabled", False):
            from app.rag.projection_cleanup import purge_registered_document
            return purge_registered_document(
                self, owner_id=owner_id, namespace=namespace, doc_id=doc_id,
            )
        from types import SimpleNamespace

        for intent in self.attempts_for_document(
            owner_id=owner_id, namespace=namespace, doc_id=doc_id
        ):
            self.delete_attempt(SimpleNamespace(**intent))
        return self.attempts_for_document(
            owner_id=owner_id, namespace=namespace, doc_id=doc_id
        )
