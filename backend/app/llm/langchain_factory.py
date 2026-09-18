"""Explicit native Claude or OpenAI-compatible LangChain chat models."""

from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from app.core.config import get_settings
from app.llm.configuration import LLMConfig, resolve_llm_config


def chat_model_from_config(
    config: LLMConfig,
    *,
    temperature: float = 0.4,
    max_tokens: int = 4096,
    timeout_seconds: int = 45,
    callbacks=None,
) -> BaseChatModel:
    if not config.configured:
        raise ValueError(f"{config.provider} chat provider is not configured")
    if max_tokens <= 0 or timeout_seconds <= 0:
        raise ValueError("Chat output limit and timeout must be positive")
    parameters = dict(
        model=config.model,
        base_url=config.base_url,
        api_key=config.api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout_seconds,
        max_retries=0,
        callbacks=callbacks,
    )
    user_clients = {}
    if config.source == "user":
        from app.llm.user_endpoint import (
            create_user_llm_async_http_client,
            create_user_llm_http_client,
        )

        user_clients = {
            "http_client": create_user_llm_http_client(timeout=timeout_seconds),
            "http_async_client": create_user_llm_async_http_client(timeout=timeout_seconds),
        }
    if config.provider == "anthropic":
        import anthropic
        from langchain_anthropic import ChatAnthropic

        model = ChatAnthropic(**parameters, anthropic_proxy=None)
        # Own the SDK clients: the integration's default HTTP client cache can
        # otherwise reuse a closed pool after an owner runtime is restarted.
        clients = dict(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )
        model._client.close()
        model._client = anthropic.Anthropic(
            **clients, **({"http_client": user_clients["http_client"]} if user_clients else {})
        )
        model._async_client = anthropic.AsyncAnthropic(
            **clients, **({"http_client": user_clients["http_async_client"]} if user_clients else {})
        )
        return model

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(**parameters, **user_clients)


def create_chat_model(settings=None, *, temperature: float = 0.4, callbacks=None):
    settings = settings or get_settings()
    return chat_model_from_config(
        resolve_llm_config(settings),
        temperature=temperature,
        timeout_seconds=settings.provider_timeout_seconds,
        callbacks=callbacks,
    )


@lru_cache()
def get_chat_model(temperature: float = 0.4) -> BaseChatModel:
    return create_chat_model(temperature=temperature)


class ChatModelCloser:
    """Close both SDK transports when their owning RAG runtime stops."""

    def __init__(self, model):
        self.model = model

    async def aclose(self):
        values = self.model.__dict__
        async_client = values.get("_async_client") or values.get("root_async_client")
        sync_client = values.get("_client") or values.get("root_client")
        try:
            if async_client is not None:
                await async_client.close()
        finally:
            if sync_client is not None:
                sync_client.close()
