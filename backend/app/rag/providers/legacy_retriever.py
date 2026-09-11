"""Dense compatibility oracle over the same authorized canonical-node projection.

This raw Chroma path is for B1 migration parity. B0's historical Agent summary
behavior is separately isolated in legacy_baseline.py and is evaluation-only.
"""

import math

from app.rag.providers.llamaindex_retriever import LlamaIndexRetriever


class LegacyDenseRetriever(LlamaIndexRetriever):
    provider_name = "legacy_dense"

    def _query(self, collection, vector, limit, where):
        result = collection.query(
            query_embeddings=[vector],
            n_results=limit,
            where=where,
            include=["distances"],
        )
        return [
            (identity, math.exp(-distance))
            for identity, distance in zip(result["ids"][0], result["distances"][0])
        ]
