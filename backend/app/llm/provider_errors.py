"""Classify transport failures without exposing upstream response bodies."""

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
