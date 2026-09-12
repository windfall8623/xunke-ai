"""Deterministic rank fusion. Distances and BM25 scores are never added."""

from app.rag.contracts import RankScore, RetrievalResult


def rrf_merge(
    rankings: list[list[str]], k: int = 60, limit: int = 40
) -> list[RankScore]:
    if k < 1 or limit < 1:
        raise ValueError("RRF k and limit must be positive")
    scores: dict[str, float] = {}
    for ranking in rankings:
        unique = list(dict.fromkeys(ranking))
        for rank, identity in enumerate(unique, 1):
            scores[identity] = scores.get(identity, 0.0) + 1.0 / (k + rank)
    return [
        RankScore(id=identity, score=score)
        for identity, score in sorted(
            scores.items(), key=lambda pair: (-pair[1], pair[0])
        )[:limit]
    ]


class HybridRetriever:
    def __init__(self, store, embedding, *, reranker=None, llm_reranker=None, build_cache=None):
        self.store, self.embedding, self.reranker = store, embedding, reranker
        self.llm_reranker = llm_reranker
        self._build_cache = build_cache if build_cache is not None else {}

    def read_build(self, manifest):
        key = (manifest.projection_key, manifest.canonical_text_hash, manifest.index_profile_hash)
        cached = self._build_cache.get(key)
        if cached is None:
            cached = self.store.read_build(manifest)
            if len(self._build_cache) >= 8:
                self._build_cache.pop(next(iter(self._build_cache)))
            self._build_cache[key] = cached
        return cached

    async def rerank_candidates(self, query, candidates, config, *, budget=None):
        from app.rag.providers.reranker import rerank

        return await rerank(
            query,
            candidates,
            config.reranker,
            provider=self.llm_reranker
            if config.reranker.provider == "llm"
            else self.reranker,
            budget=budget,
            limit=config.final_top_k,
        )

    async def retrieve_evidence(
        self, query, scope, config, *, budget=None
    ) -> RetrievalResult:
        from app.rag.errors import SourceUnavailable
        from app.rag.providers.legacy_retriever import LegacyDenseRetriever
        from app.rag.providers.lexical import LexicalIndex
        from app.rag.providers.llamaindex_retriever import LlamaIndexRetriever
        from app.rag.scope import evidence_in_scope

        builds = [self.read_build(source) for source in scope.documents]
        if any(
            b.profile.profile_id != config.index_profile_id
            or (
                config.index_profile_hash
                and b.index_profile_hash != config.index_profile_hash
            )
            for b in builds
        ):
            raise SourceUnavailable("Selected source needs a compatible index rebuild")
        if len({b.index_profile_hash for b in builds}) > 1:
            raise SourceUnavailable("Selected sources use incompatible index profiles")
        evidence_map, rankings = {}, {}
        if config.retriever != "bm25":
            provider = (
                LegacyDenseRetriever
                if config.retriever == "legacy_dense"
                else LlamaIndexRetriever
            )
            dense = await provider(self.store, self.embedding).retrieve_evidence(
                query, scope, config, budget=budget
            )
            evidence_map.update({e.evidence_id: e for e in dense.candidates})
            rankings["dense"] = [e.evidence_id for e in dense.candidates]
        if config.retriever in ("hybrid", "bm25"):
            combined = LexicalIndex([])
            nodes = {}
            for built in builds:
                lexical = LexicalIndex.load(
                    self.store.resolve_key(built.projection_key + "/lexical.json")
                )
                for node in built.nodes:
                    if not node.is_parent and evidence_in_scope(node.evidence, scope):
                        nodes[node.node_id] = node.evidence
                        combined.tokens[node.node_id] = lexical.tokens[node.node_id]
            ranked = combined.search(
                query, allowed_ids=set(nodes), top_k=config.lexical_top_k
            )
            rankings["lexical"] = []
            for item in ranked:
                evidence = nodes[item.id]
                old = evidence_map.get(evidence.evidence_id, evidence)
                evidence_map[evidence.evidence_id] = old.model_copy(
                    update={
                        "retrieval_scores": {
                            **old.retrieval_scores,
                            "lexical": item.score,
                        }
                    }
                )
                rankings["lexical"].append(evidence.evidence_id)
        if config.retriever == "hybrid":
            fused = rrf_merge(
                list(rankings.values()), config.rrf_k, config.candidate_limit
            )
            candidates = [
                evidence_map[r.id].model_copy(
                    update={
                        "score": r.score,
                        "retrieval_scores": {
                            **evidence_map[r.id].retrieval_scores,
                            "rrf": r.score,
                        },
                    }
                )
                for r in fused
            ]
        else:
            order = next(iter(rankings.values()), [])
            candidates = [
                evidence_map[identity] for identity in order[: config.candidate_limit]
            ]
        ranked = await self.rerank_candidates(
            query,
            candidates,
            config,
            budget=budget,
        )
        return RetrievalResult(
            evidence=ranked.evidence,
            candidates=candidates,
            rankings=rankings,
            status="ready" if ranked.evidence else "empty",
            warnings=ranked.warnings,
            effective_config={
                "retriever": config.retriever,
                "reranker": ranked.effective_config,
            },
            usage=budget.snapshot() if budget else {},
        )
