"""Immutable canonical files and attempt-isolated, single-owner Chroma projection.

SQL remains authoritative for ready/active pointers and authorization. A stored
candidate is not discoverable without its exact manifest in an authorized scope.
Deletion callers must fence/wait for in-flight jobs, then sweep again until empty.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
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
from app.rag.ingestion import load_canonical_document_bounded
from app.rag.providers.lexical import LexicalIndex
from app.rag.structure import chunk_document


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
        path = self.resolve_key(key)
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and immutable:
            if json.loads(path.read_bytes()) != payload:
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

    @staticmethod
    def _collection_name(key: str) -> str:
        return "rag_" + stable_hash(key)[:48]

    def _collection(self, key: str):
        self._check_owner()
        return self._client.get_collection(
            self._collection_name(key), embedding_function=None
        )

    async def build(self, request: BuildRequest, embedding, budget=None) -> BuildResult:
        self._check_owner()
        async with self._build_lock:
            document = request.canonical or await asyncio.to_thread(
                load_canonical_document_bounded, request.source
            )
            if (
                request.profile.embedding_model != embedding.model
                or request.profile.embedding_dimensions != embedding.dimensions
            ):
                raise SourceUnavailable(
                    "Embedding adapter and index profile are incompatible"
                )
            key = projection_key(
                document.owner_id,
                document.namespace,
                document.doc_id,
                document.document_version_id,
                document.parse_artifact_id,
                request.index_build_id,
                request.attempt_id,
            )
            manifest_path = self.resolve_key(key + "/manifest.json")
            if manifest_path.exists():
                prior = BuildResult.model_validate_json(manifest_path.read_bytes())
                if prior.index_profile_hash != request.profile.profile_hash:
                    raise SourceUnavailable(
                        "Attempt already uses a different index profile"
                    )
                self._validate_build(prior)
                return prior
            nodes = chunk_document(
                document, request.profile, request.index_build_id, request.attempt_id
            )
            children = [n for n in nodes if not n.is_parent]
            if not children:
                raise SourceUnavailable("No indexable source spans")
            vectors = await embedding.embed_documents(
                [n.embedding_text for n in children], budget=budget
            )
            if len(vectors) != len(children) or any(
                len(v) != embedding.dimensions or any(not math.isfinite(x) for x in v)
                for v in vectors
            ):
                raise SourceUnavailable(
                    "Embedding vector count or dimensions do not match"
                )
            canonical_key = self.save_canonical(
                document, request.canonical_artifact_key
            )
            intent = {
                "owner_id": document.owner_id,
                "namespace": document.namespace,
                "doc_id": document.doc_id,
                "document_version_id": document.document_version_id,
                "parse_artifact_id": document.parse_artifact_id,
                "index_build_id": request.index_build_id,
                "attempt_id": request.attempt_id,
                "projection_key": key,
            }
            self.put_json(key + "/attempt.json", intent)
            with self._io_lock:
                from llama_index.core.schema import (
                    NodeRelationship,
                    RelatedNodeInfo,
                    TextNode,
                )
                from llama_index.core.storage.docstore import SimpleDocumentStore
                from llama_index.vector_stores.chroma import ChromaVectorStore

                name = self._collection_name(key)
                existing = {c.name for c in self._client.list_collections()}
                if name in existing:
                    # Exact attempt retry only; no active pointer is changed.
                    self._client.delete_collection(name)
                collection = self._client.create_collection(
                    name=name,
                    embedding_function=None,
                    # Small immutable collections never reach Chroma's default
                    # 1000-vector sync threshold. A segment can then be evicted
                    # before files exist, causing "Nothing found on disk" in
                    # later reads from this same owner. Materialize at least one
                    # complete batch before validating/publishing the build.
                    configuration={
                        "hnsw": {
                            "space": "cosine",
                            "batch_size": min(100, len(children)),
                            "sync_threshold": min(100, len(children)),
                        }
                    },
                    metadata={
                        "projection_key": key,
                        "owner_id": document.owner_id,
                        "namespace": document.namespace,
                        "doc_id": document.doc_id,
                    },
                )
                vector_by_id = {n.node_id: v for n, v in zip(children, vectors)}
                llama_nodes = []
                for node in nodes:
                    metadata = {
                        "owner_id": document.owner_id,
                        "namespace": document.namespace,
                        "scope_doc_id": document.doc_id,
                        "document_version_id": document.document_version_id,
                        "parse_artifact_id": document.parse_artifact_id,
                        "index_build_id": request.index_build_id,
                        "attempt_id": request.attempt_id,
                        "scope_node_id": node.node_id,
                    }
                    relationships = {
                        NodeRelationship.SOURCE: RelatedNodeInfo(
                            node_id=document.document_version_id
                        )
                    }
                    if node.parent_id:
                        relationships[NodeRelationship.PARENT] = RelatedNodeInfo(
                            node_id=node.parent_id
                        )
                    llama_nodes.append(
                        TextNode(
                            id_=node.node_id,
                            text=node.embedding_text,
                            embedding=vector_by_id.get(node.node_id),
                            metadata=metadata,
                            excluded_embed_metadata_keys=list(metadata),
                            excluded_llm_metadata_keys=list(metadata),
                            relationships=relationships,
                            start_char_idx=node.evidence.locator.start_char,
                            end_char_idx=node.evidence.locator.end_char,
                        )
                    )
                docstore = SimpleDocumentStore()
                docstore.add_documents(llama_nodes)
                docstore.persist(str(self.resolve_key(key + "/docstore.json")))
                ChromaVectorStore(chroma_collection=collection).add(
                    [n for n in llama_nodes if n.node_id in vector_by_id]
                )
                LexicalIndex(
                    [{"id": n.node_id, "text": n.embedding_text} for n in children],
                    tokenizer_version=request.profile.tokenizer_version,
                ).persist(self.resolve_key(key + "/lexical.json"))
                result = BuildResult(
                    owner_id=document.owner_id,
                    namespace=document.namespace,
                    doc_id=document.doc_id,
                    document_version_id=document.document_version_id,
                    source_sha256=document.source_sha256,
                    parse_artifact_id=document.parse_artifact_id,
                    canonical_text_hash=document.canonical_text_hash,
                    index_build_id=request.index_build_id,
                    attempt_id=request.attempt_id,
                    profile=request.profile,
                    index_profile_hash=request.profile.profile_hash,
                    node_count=len(children),
                    embedding_dimensions=embedding.dimensions,
                    projection_key=key,
                    canonical_artifact_key=canonical_key,
                    nodes=nodes,
                    checksum=stable_hash([n.model_dump(mode="json") for n in nodes]),
                    expected_document_revision=request.expected_document_revision,
                    title=document.title,
                )
                self._validate_build(result)
                self.put_json(key + "/manifest.json", result.model_dump(mode="json"))
                return result

    def _validate_build(self, result: BuildResult) -> None:
        if (
            result.projection_key != self._key(result)
            or result.index_profile_hash != result.profile.profile_hash
        ):
            raise SourceUnavailable("Index manifest identity does not match")
        if result.checksum != stable_hash(
            [n.model_dump(mode="json") for n in result.nodes]
        ):
            raise SourceUnavailable("Index node checksum does not match")
        document = self.load_canonical(result.canonical_artifact_key)
        if document.canonical_text_hash != result.canonical_text_hash:
            raise SourceUnavailable("Canonical and index versions do not match")
        children = [n for n in result.nodes if not n.is_parent]
        for node in result.nodes:
            evidence = node.evidence
            if (
                document.text[evidence.locator.start_char : evidence.locator.end_char]
                != evidence.excerpt
            ):
                raise SourceUnavailable("Index quote differs from canonical source")
        collection = self._collection(result.projection_key)
        stored = collection.get(include=["embeddings"])
        if len(children) != result.node_count or set(stored["ids"]) != {
            n.node_id for n in children
        }:
            raise SourceUnavailable("Index vector count or identity does not match")
        if any(len(v) != result.embedding_dimensions for v in stored["embeddings"]):
            raise SourceUnavailable("Index embedding dimensions do not match")
        from llama_index.core.storage.docstore import SimpleDocumentStore

        docstore = SimpleDocumentStore.from_dict(
            json.loads(
                self.resolve_key(result.projection_key + "/docstore.json").read_bytes()
            )
        )
        for node in result.nodes:
            restored = docstore.get_document(node.node_id)
            if restored.text != node.embedding_text:
                raise SourceUnavailable("Docstore text does not match source")
        lexical = LexicalIndex.load(
            self.resolve_key(result.projection_key + "/lexical.json")
        )
        if set(lexical.tokens) != {n.node_id for n in children}:
            raise SourceUnavailable("Lexical projection identity does not match")

    def read_build(self, manifest: SourceManifest) -> BuildResult:
        self._check_owner()
        key = self._key(manifest)
        if manifest.projection_key and manifest.projection_key != key:
            raise SourceUnavailable("Projection key does not match authorized manifest")
        try:
            result = BuildResult.model_validate_json(
                self.resolve_key(key + "/manifest.json").read_bytes()
            )
            expected = (
                manifest.owner_id,
                manifest.namespace,
                manifest.doc_id,
                manifest.document_version_id,
                manifest.parse_artifact_id,
                manifest.index_build_id,
                manifest.attempt_id,
                manifest.canonical_text_hash,
            )
            actual = (
                result.owner_id,
                result.namespace,
                result.doc_id,
                result.document_version_id,
                result.parse_artifact_id,
                result.index_build_id,
                result.attempt_id,
                result.canonical_text_hash,
            )
            if expected != actual or (
                manifest.index_profile_hash
                and manifest.index_profile_hash != result.index_profile_hash
            ):
                raise SourceUnavailable(
                    "Index manifest differs from the authorized source"
                )
            self._validate_build(result)
            return result
        except SourceUnavailable:
            raise
        except Exception as exc:
            raise SourceUnavailable(
                "Required index build is missing, corrupt, or awaiting rebuild"
            ) from exc

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
        with self._io_lock:
            name = self._collection_name(key)
            if name in {c.name for c in self._client.list_collections()}:
                self._client.delete_collection(name)
            path = self.resolve_key(key)
            projection_root = self.resolve_key("rag/projections")
            if not path.is_relative_to(projection_root) or path == projection_root:
                raise SourceUnavailable("Cleanup path is outside its attempt")
            if path.exists():
                shutil.rmtree(path)

    def projection_exists(self, manifest) -> bool:
        self._check_owner()
        key = self._key(manifest)
        return self.resolve_key(key).exists() or self._collection_name(key) in {
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
        from types import SimpleNamespace

        for intent in self.attempts_for_document(
            owner_id=owner_id, namespace=namespace, doc_id=doc_id
        ):
            self.delete_attempt(SimpleNamespace(**intent))
        return self.attempts_for_document(
            owner_id=owner_id, namespace=namespace, doc_id=doc_id
        )
