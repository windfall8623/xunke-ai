"""Dense compatibility oracle over the same authorized canonical-node projection.

This raw Chroma path is for B1 migration parity. B0's historical Agent summary
behavior is separately isolated in legacy_baseline.py and is evaluation-only.
"""

from app.rag.providers.llamaindex_retriever import LlamaIndexRetriever


class LegacyDenseRetriever(LlamaIndexRetriever):
    provider_name = "legacy_dense"

    def _score(self, raw_score: float, score_version="chroma-cosine-distance-v1") -> float:
        return super()._score(raw_score, score_version)
