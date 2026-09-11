"""JSON-only chat-ranking configuration, safe for the API without model SDKs."""

from app.llm.configuration import resolve_llm_config
from app.rag.contracts import LLMRerankerConfig, RerankerConfig, text_hash


def llm_reranker_config(settings) -> RerankerConfig:
    selected = resolve_llm_config(settings)
    if not selected.configured:
        raise ValueError("LLM reranking requires a configured generator provider")
    return RerankerConfig(
        provider="llm",
        timeout_seconds=min(
            settings.reranker_llm_timeout_seconds, settings.provider_timeout_seconds
        ),
        llm=LLMRerankerConfig(
            provider=selected.provider,
            model=selected.model,
            endpoint_hash=text_hash(selected.base_url),
            max_input_tokens=settings.reranker_llm_max_input_tokens,
            max_output_tokens=settings.reranker_llm_max_output_tokens,
        ),
    )
