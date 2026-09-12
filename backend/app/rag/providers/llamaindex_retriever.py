"""LlamaIndex Chroma adapter returning only project Evidence contracts.

检索经 VectorProjectionStore 抽象执行（过滤在 top-k 之前生效），
不再直接访问底层 Chroma collection；分数由子类按 metric 换算。
"""

from __future__ import annotations

import logging

from app.rag.contracts import PipelineConfig, ResolvedScope, RetrievalResult
from app.rag.errors import RetrievalUnavailable, SourceUnavailable
from app.rag.scope import evidence_in_scope


class LlamaIndexRetriever:
    provider_name = "llamaindex_dense"

    def __init__(self, store, embedding):
        self.store, self.embedding = store, embedding

    def _score(self, raw_score: float, score_version="chroma-cosine-distance-v1") -> float:
        # 与 llama-index Chroma 适配器一致：similarity = exp(-cosine_distance)。
        import math

        # Keep the established score scale when Qdrant returns cosine similarity.
        distance = 1.0 - raw_score if score_version.startswith("qdrant-") else raw_score
        return math.exp(-distance)

    async def retrieve_evidence(
        self, query: str, scope: ResolvedScope, config: PipelineConfig, *, budget=None
    ) -> RetrievalResult:
        logging.getLogger("llama_index.vector_stores.chroma.base").setLevel(
            logging.WARNING
        )
        from app.rag.index_artifacts import ref_from_manifest
        from app.rag.vector_store import VectorSearch

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
        if hasattr(self.embedding, "cached_embed_query"):
            vector = await self.embedding.cached_embed_query(
                query, owner_id=scope.owner_id, namespace=scope.namespace,
                mode="production" if scope.namespace == "production" else "evaluation",
                budget=budget,
            )
        else:
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
                # 投影层在 top-k 之前应用白名单过滤，绝不先全库 top-k 再过滤。
                hits = await self.store.search(
                    VectorSearch(
                        query_vector=vector,
                        ref=ref_from_manifest(manifest),
                        allowed_node_ids=frozenset(by_id),
                        top_k=min(config.dense_top_k, len(by_id)),
                        deadline_seconds=budget.remaining_seconds if budget else None,
                    )
                )
                for hit in hits:
                    if hit.node_id not in by_id:
                        raise SourceUnavailable(
                            "Retriever returned an unauthorized source"
                        )
                    candidates.append(
                        by_id[hit.node_id].evidence.model_copy(
                            update={
                                "score": self._score(hit.raw_score, hit.score_version),
                                "retrieval_scores": {
                                    "dense": self._score(hit.raw_score, hit.score_version)
                                },
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
