"""Named bounded pipeline profiles. Real model/provider selection stays explicit."""

from app.rag.contracts import IndexProfile, PipelineConfig

PIPELINE_IDS = (
    "legacy-summary-b0",
    "legacy-dense-v1",
    "llamaindex-dense-v1",
    "bm25-v1",
    "hybrid-v1",
    "hybrid-rerank-v1",
    "hybrid-llm-rerank-v1",
    "structure-v1",
    "ablation-char-v1",
    "ablation-structure-v1",
    "ablation-parent-v1",
    "ablation-coverage-v1",
)


def get_pipeline_config(pipeline_id="hybrid-v1", **overrides) -> PipelineConfig:
    presets = {
        "legacy-summary-b0": {
            "retriever": "legacy_dense",
            "dense_top_k": 4,
            "final_top_k": 4,
            "require_semantic_validation": False,
        },
        "legacy-dense-v1": {"retriever": "legacy_dense"},
        "llamaindex-dense-v1": {"retriever": "llamaindex_dense"},
        "bm25-v1": {"retriever": "bm25"},
        "hybrid-v1": {"retriever": "hybrid"},
        "hybrid-rerank-v1": {"retriever": "hybrid"},
        "hybrid-llm-rerank-v1": {"retriever": "hybrid"},
        "structure-v1": {
            "retriever": "hybrid",
            "index_profile_id": "structure-token-v1",
            "parent_expansion": True,
        },
        # Adjacent profiles change only chunking, parent expansion, then
        # catalog coverage. Existing profile IDs retain their original behavior.
        "ablation-char-v1": {
            "retriever": "hybrid",
            "coverage_strategy": "single-goal-v1",
        },
        "ablation-structure-v1": {
            "retriever": "hybrid",
            "index_profile_id": "structure-token-v1",
            "coverage_strategy": "single-goal-v1",
        },
        "ablation-parent-v1": {
            "retriever": "hybrid",
            "index_profile_id": "structure-token-v1",
            "parent_expansion": True,
            "coverage_strategy": "single-goal-v1",
        },
        "ablation-coverage-v1": {
            "retriever": "hybrid",
            "index_profile_id": "structure-token-v1",
            "parent_expansion": True,
            "coverage_strategy": "catalog-v1",
        },
    }
    if pipeline_id not in presets:
        raise ValueError("Unknown pipeline configuration")
    result = PipelineConfig.model_validate(
        {"pipeline_version": pipeline_id, **presets[pipeline_id], **overrides}
    )
    if pipeline_id == "hybrid-rerank-v1" and result.reranker.provider == "none":
        raise ValueError(
            "Rerank pipeline requires an explicit pinned reranker configuration"
        )
    if pipeline_id == "hybrid-llm-rerank-v1" and result.reranker.provider != "llm":
        raise ValueError("LLM rerank pipeline requires explicit chat configuration")
    if pipeline_id == "legacy-summary-b0" and (
        not result.legacy_source_archive_sha256 or not result.legacy_source_commit
    ):
        raise ValueError(
            "Legacy baseline requires a pinned source archive hash and commit"
        )
    return result


def get_index_profile(profile_id="legacy-char-v1", **overrides) -> IndexProfile:
    if profile_id not in ("legacy-char-v1", "structure-token-v1"):
        raise ValueError("Unknown index profile")
    return IndexProfile.model_validate(
        {
            "profile_id": profile_id,
            "chunker": "structure_token"
            if profile_id == "structure-token-v1"
            else "recursive_character",
            **overrides,
        }
    )
