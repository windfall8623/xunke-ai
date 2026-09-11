"""Resolve image credentials without forwarding embedding keys across providers."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit


@dataclass(frozen=True)
class ImageProviderConfig:
    base_url: str
    api_key: str = field(repr=False)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.api_key != "sk-xxx")


def _https_base(value: str) -> str:
    base = value.strip().rstrip("/")
    try:
        parsed = urlsplit(base)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
        ):
            return ""
    except ValueError:
        return ""
    return base


def _native_dashscope_base(value: str) -> str:
    base = _https_base(value)
    if not base:
        return ""
    parsed = urlsplit(base)
    official = parsed.hostname in {
        "dashscope.aliyuncs.com",
        "dashscope-intl.aliyuncs.com",
        "dashscope-us.aliyuncs.com",
    } or parsed.hostname.endswith(".maas.aliyuncs.com")
    if (
        not official
        or parsed.port not in (None, 443)
        or parsed.path not in ("", "/compatible-mode/v1", "/api/v1")
    ):
        return ""
    return urlunsplit((parsed.scheme, parsed.netloc, "/api/v1", "", ""))


def resolve_image_config(settings=None) -> ImageProviderConfig:
    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    native_base = _native_dashscope_base(settings.dashscope_base_url)
    supplied_base = settings.dashscope_image_base_url.strip()
    base = _https_base(supplied_base) if supplied_base else native_base
    key = settings.dashscope_image_api_key.strip()
    if (
        not key
        and native_base
        and (not supplied_base or _native_dashscope_base(supplied_base) == base)
    ):
        key = settings.dashscope_api_key.strip()
    # A third-party embedding endpoint supplies neither an implicit image
    # endpoint nor credentials for an explicitly configured image gateway.
    return ImageProviderConfig(base_url=base, api_key=key)
