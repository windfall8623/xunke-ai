"""One explicit provider identity for execution, readiness and frozen evaluation."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: str = field(repr=False)

    def __post_init__(self):
        if self.provider not in {"deepseek", "anthropic", "openai_compatible"}:
            raise ValueError("Unknown LLM_PROVIDER")
        endpoint = self.base_url.strip().rstrip("/")
        if endpoint:
            parsed = urlsplit(endpoint)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "LLM base URL must be HTTP(S), without credentials or query"
                )
            if self.provider == "anthropic":
                if parsed.path.endswith("/messages"):
                    raise ValueError(
                        "ANTHROPIC_BASE_URL must be an API root, not /messages"
                    )
                # The native SDK adds /v1/messages itself; accept either common
                # base URL spelling without sending /v1/v1/messages.
                if parsed.path.endswith("/v1"):
                    endpoint = endpoint[:-3]
        object.__setattr__(self, "base_url", endpoint)
        object.__setattr__(self, "model", self.model.strip())
        object.__setattr__(self, "api_key", self.api_key.strip())

    @property
    def configured(self) -> bool:
        return bool(
            self.api_key and self.api_key != "sk-xxx" and self.model and self.base_url
        )


def resolve_llm_config(settings=None) -> LLMConfig:
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    provider = settings.llm_provider
    prefix = {
        "deepseek": "deepseek",
        "anthropic": "anthropic",
        "openai_compatible": "llm",
    }.get(provider)
    if prefix is None:
        raise ValueError("Unknown LLM_PROVIDER")
    return LLMConfig(
        provider=provider,
        model=getattr(settings, f"{prefix}_model"),
        base_url=getattr(settings, f"{prefix}_base_url"),
        api_key=getattr(settings, f"{prefix}_api_key"),
    )
