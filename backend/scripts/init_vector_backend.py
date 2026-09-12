"""Explicitly initialize fixed Qdrant vector spaces using environment credentials.

Run from backend: python -m scripts.init_vector_backend --space-config spaces.json
The JSON format is {"spaces": [{"embedding_signature_hash": "...", "dimensions":
1024, "target_revision": "qdrant-v1"}]}. A single space can also be supplied with
--embedding-signature-hash HASH --dimensions N --target-revision REVISION.
No model is called; existing collections are checked and never reset.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import get_settings
from app.rag.errors import RagError
from app.rag.providers.qdrant_projection import (
    DENSE_VECTOR_NAME,
    QdrantProjectionStore,
    VectorOperationUnconfirmed,
    collection_name_for,
)
from app.rag.vector_store import BACKEND_QDRANT, PROJECTION_SCHEMA_VERSION, ProjectionRef


class VectorSpace(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    embedding_signature_hash: str = Field(min_length=1, max_length=512)
    dimensions: int = Field(gt=0)
    target_revision: str | None = Field(default=None, min_length=1, max_length=512)
    schema_version: str = PROJECTION_SCHEMA_VERSION


class SpaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    spaces: list[VectorSpace] = Field(min_length=1)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or check fixed Qdrant spaces and payload indexes.")
    parser.add_argument("--space-config", type=Path, help="JSON file containing a nonempty spaces array")
    parser.add_argument("--embedding-signature-hash", help="Verified embedding space signature for one collection")
    parser.add_argument("--dimensions", type=int, help="Actual vector dimensions; no embedding request is made")
    parser.add_argument("--target-revision", help="Default storage revision (otherwise VECTOR_TARGET_REVISION)")
    parser.add_argument("--collection-prefix", help="Collection prefix (otherwise QDRANT_COLLECTION_PREFIX)")
    return parser


def _load_spaces(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[VectorSpace]:
    if args.space_config is not None:
        if args.embedding_signature_hash is not None or args.dimensions is not None:
            parser.error("use either --space-config or the single-space arguments")
        try:
            return SpaceConfig.model_validate_json(args.space_config.read_text(encoding="utf-8")).spaces
        except (OSError, ValidationError) as exc:
            parser.error(f"cannot read a valid fixed-space configuration ({type(exc).__name__})")
    if args.embedding_signature_hash is None or args.dimensions is None:
        parser.error("provide --space-config or both --embedding-signature-hash and --dimensions")
    try:
        return [VectorSpace(embedding_signature_hash=args.embedding_signature_hash, dimensions=args.dimensions)]
    except ValidationError:
        parser.error("single-space dimensions must be positive and the signature must be nonempty")
    raise AssertionError("argparse.error must exit")


def _resolved_spaces(spaces: list[VectorSpace], args: argparse.Namespace, settings) -> list[tuple[ProjectionRef, int]]:
    resolved: dict[str, tuple[ProjectionRef, int]] = {}
    for space in spaces:
        revision = space.target_revision or args.target_revision or settings.vector_target_revision
        name = collection_name_for(
            space.embedding_signature_hash, revision,
            prefix=args.collection_prefix or settings.qdrant_collection_prefix,
        )
        # Collection initialization stores only space metadata. These required
        # logical fields are placeholders and are never written as point payload.
        ref = ProjectionRef(
            backend=BACKEND_QDRANT, target_revision=revision, collection_name=name,
            schema_version=space.schema_version, projection_key="initialization/" + name,
            owner_id=1, namespace="initialization", doc_id="initialization",
            document_version_id="initialization", parse_artifact_id="initialization",
            index_build_id="initialization", attempt_id="initialization",
            index_profile_hash="collection-initialization",
            embedding_signature_hash=space.embedding_signature_hash,
        )
        previous = resolved.get(name)
        if previous is not None and (previous[1] != space.dimensions or previous[0].schema_version != ref.schema_version):
            raise ValueError("A fixed vector space has conflicting dimensions or schema versions")
        resolved[name] = (ref, space.dimensions)
    return list(resolved.values())


async def _initialize(spaces: list[tuple[ProjectionRef, int]], settings) -> list[dict]:
    store = QdrantProjectionStore(
        settings.qdrant_url, api_key=settings.qdrant_api_key,
        read_only_api_key=settings.qdrant_read_only_api_key, writable=True,
        search_timeout_seconds=settings.qdrant_search_timeout_seconds,
        write_timeout_seconds=settings.qdrant_write_timeout_seconds,
        rpc_concurrency=settings.qdrant_rpc_concurrency,
        batch_size=settings.qdrant_batch_size,
        max_request_bytes=settings.qdrant_max_request_bytes,
        hnsw_ef_search=settings.qdrant_hnsw_ef_search,
        vector_on_disk=settings.qdrant_vector_on_disk,
        hnsw_m=settings.qdrant_hnsw_m,
        hnsw_ef_construct=settings.qdrant_hnsw_ef_construct,
    )
    initialized = []
    try:
        for ref, dimensions in spaces:
            await store.initialize_collection(ref, dimensions)
            initialized.append({
                "collection_name": ref.collection_name,
                "embedding_signature_hash": ref.embedding_signature_hash,
                "target_revision": ref.target_revision, "schema_version": ref.schema_version,
                "dimensions": dimensions, "vector_name": DENSE_VECTOR_NAME, "distance": "Cosine",
            })
    finally:
        await store.close()
    return initialized


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    spaces = _load_spaces(args, parser)
    try:
        settings = get_settings()
        resolved = _resolved_spaces(spaces, args, settings)
        initialized = asyncio.run(_initialize(resolved, settings))
    except VectorOperationUnconfirmed as exc:
        print(json.dumps({
            "status": "unknown", "error": exc.code,
            "provider_operation_id": exc.provider_operation_id,
        }), file=sys.stderr)
        return 3
    except (RagError, ValueError) as exc:
        message = exc.message if isinstance(exc, RagError) else "Invalid Qdrant initialization configuration"
        print(json.dumps({"status": "failed", "error": type(exc).__name__, "message": message}), file=sys.stderr)
        return 2
    except Exception as exc:
        # SDK errors can embed response bodies; do not print payloads or keys.
        print(json.dumps({"status": "failed", "error": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps({"backend": BACKEND_QDRANT, "status": "initialized", "collections": initialized}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
