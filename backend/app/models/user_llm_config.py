"""Strict self-service provider API contract; secrets never appear in views."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Provider = Literal["deepseek", "anthropic", "openai_compatible"]


class LLMConfigRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider: Provider
    model: str = Field(min_length=1, max_length=128)
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str | None = Field(default=None, min_length=8, max_length=512, repr=False)

    @field_validator("model", "api_key")
    @classmethod
    def no_control_characters(cls, value):
        if value is not None and any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise ValueError("Control characters are not allowed")
        return value


class LLMConfigView(BaseModel):
    configured: bool
    provider: Provider | None
    model: str | None
    base_url: str | None
    api_key_hint: str | None
    can_use_system: bool
    source: Literal["user", "system"] | None
