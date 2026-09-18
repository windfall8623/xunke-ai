"""Classify transport failures; user-owned providers expose only sanitized messages."""

import httpx

from app.rag.errors import ProviderRateLimited, ProviderTimeout, ProviderUnavailable


def provider_failure(error: BaseException):
    # Load optional chat SDKs only at a failed external-call boundary. A plain
    # TimeoutError or CancelledError may be our own job deadline, not the SDK's.
    import anthropic
    import openai

    if isinstance(
        error,
        (httpx.TimeoutException, anthropic.APITimeoutError, openai.APITimeoutError),
    ):
        return ProviderTimeout("Model service response timed out")
    # SDK timeout errors also inherit APIConnectionError; classify them first.
    if isinstance(
        error,
        (httpx.NetworkError, anthropic.APIConnectionError, openai.APIConnectionError),
    ):
        return ProviderUnavailable("Model service is temporarily unreachable")
    if isinstance(
        error, (httpx.HTTPStatusError, anthropic.APIStatusError, openai.APIStatusError)
    ):
        status = error.response.status_code
        if status == 429:
            return ProviderRateLimited("Model service returned HTTP 429; retry later")
    return None


def user_provider_failure(error: BaseException, *, api_key: str):
    import re
    import unicodedata

    import anthropic
    import openai

    from app.core.errors import AppError

    response = getattr(error, "response", None)
    if isinstance(error, (httpx.HTTPStatusError, anthropic.APIStatusError, openai.APIStatusError)):
        status = response.status_code
        body = getattr(error, "body", None)
        if not isinstance(body, dict):
            try:
                body = response.json()
            except (ValueError, AttributeError):
                body = {}
        detail = body.get("error", body) if isinstance(body, dict) else {}
        message = detail.get("message", "") if isinstance(detail, dict) else ""
        if not isinstance(message, str):
            message = ""
        message = "".join(ch for ch in message if not unicodedata.category(ch).startswith("C"))
        if api_key:
            message = message.replace(api_key, "[已隐藏]")
        message = re.sub(r"(?i)bearer\s+\S+", "[已隐藏]", message)
        message = re.sub(r"(?i)((?:api[_-]?key|authorization)\s*[:=]\s*)\S+", r"\1[已隐藏]", message)
        message = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[已隐藏]", message)
        message = message[:750]
        detail_text = f"（HTTP {status}）" + (f"：{message}" if message else "")
    else:
        failure = provider_failure(error)
        if failure is None:
            return None
        detail_text = {
            "PROVIDER_TIMEOUT": "：模型服务响应超时",
            "PROVIDER_UNAVAILABLE": "：无法连接模型服务",
            "PROVIDER_RATE_LIMITED": "：模型服务限流",
        }.get(failure.code, "")
    return AppError(422, "user_llm_failed", f"自有模型调用失败{detail_text}。请在个人中心检查自有模型配置、余额和额度。")
