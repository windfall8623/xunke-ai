"""LlamaIndex Chroma adapter returning only project Evidence contracts."""

from __future__ import annotations

import logging

from app.rag.contracts import PipelineConfig, ResolvedScope, RetrievalResult
from app.rag.errors import RetrievalUnavailable, SourceUnavailable
from app.rag.scope import evidence_in_scope


class LlamaIndexRetriever:
    provider_name = "llamaindex_dense"

    def __init__(self, store, embedding):
        self.store, self.embedding = store, embedding

    async def retrieve_evidence(
        self, query: str, scope: ResolvedScope, config: PipelineConfig, *, budget=None
    ) -> RetrievalResult:
        logging.getLogger("llama_index.vector_stores.chroma.base").setLevel(
            logging.WARNING
        )
        builds = []
        for manifest in scope.documents:
            built = self.store.read_build(manifest)
            if (
                built.profile.profile_id != config.index_profile_id
                or (
                    config.index_profile_hash
                    and built.index_profile_hash != config.index_profile_hash
                )
                or built.profile.embedding_model != self.embedding.model
                or built.embedding_dimensions != self.embedding.dimensions
            ):
                raise SourceUnavailable(
                    "Selected source needs a compatible index rebuild"
                )
            builds.append((manifest, built))
        if len({b.index_profile_hash for _, b in builds}) > 1:
            raise SourceUnavailable(
                "Cannot search incompatible index profiles together"
            )
        if not builds:
            return RetrievalResult(status="empty")
        vector = await self.embedding.embed_query(query, budget=budget)
        candidates = []
        try:
            for manifest, built in builds:
                by_id = {
                    n.node_id: n
                    for n in built.nodes
                    if not n.is_parent and evidence_in_scope(n.evidence, scope)
                }
                if not by_id:
                    continue
                # Chroma applies this whitelist before n_results, never after global top-k.
                where = {
                    "$and": [
                        {"owner_id": scope.owner_id},
                        {"namespace": scope.namespace},
                        {"scope_doc_id": manifest.doc_id},
                        {"document_version_id": manifest.document_version_id},
                        {"parse_artifact_id": manifest.parse_artifact_id},
                        {"index_build_id": manifest.index_build_id},
                        {"attempt_id": manifest.attempt_id},
                        {"scope_node_id": {"$in": sorted(by_id)}},
                    ]
                }
                result = self._query(
                    self.store._collection(built.projection_key),
                    vector,
                    min(config.dense_top_k, len(by_id)),
                    where,
                )
                for identity, score in result:
                    if identity not in by_id:
                        raise SourceUnavailable(
                            "Retriever returned an unauthorized source"
                        )
                    candidates.append(
                        by_id[identity].evidence.model_copy(
                            update={
                                "score": score,
                                "retrieval_scores": {"dense": score},
                            }
                        )
                    )
        except SourceUnavailable:
            raise
        except Exception as exc:
            raise RetrievalUnavailable("Dense retrieval is unavailable") from exc
        candidates.sort(key=lambda item: (-(item.score or 0), item.evidence_id))
        candidates = candidates[: config.dense_top_k]
        return RetrievalResult(
            evidence=candidates[: config.final_top_k],
            candidates=candidates,
            rankings={"dense": [e.evidence_id for e in candidates]},
            status="ready" if candidates else "empty",
            effective_config={"retriever": self.provider_name},
            usage=budget.snapshot() if budget else {},
        )

    def _query(self, collection, vector, limit, where):
        from llama_index.core.vector_stores.types import VectorStoreQuery
        from llama_index.vector_stores.chroma import ChromaVectorStore

        result = ChromaVectorStore(chroma_collection=collection).query(
            VectorStoreQuery(query_embedding=vector, similarity_top_k=limit),
            where=where,
        )
        return list(zip(result.ids, result.similarities))
