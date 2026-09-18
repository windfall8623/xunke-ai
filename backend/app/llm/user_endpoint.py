"""Public-only HTTP transports for untrusted user provider endpoints.

Resolve every request, reject the entire DNS answer if any address is not public,
and connect to a validated literal IP (not a second DNS lookup). Preserve Host
and TLS SNI/certificate verification. Never use environment proxies or redirects.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from app.core.errors import AppError


def _invalid():
    return AppError(422, "invalid_llm_endpoint", "模型地址必须是公开 HTTP(S) API 地址，不能使用内网地址或重定向")


def normalize_user_llm_endpoint(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or "\\" in value
            or any(ord(char) < 33 or ord(char) == 127 for char in value)
            or "%" in parsed.netloc
        ):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            pass  # Hostnames are validated by DNS at the transport boundary.
        else:
            if not _public(address):
                raise ValueError
    except (ValueError, TypeError):
        raise _invalid() from None
    return value


def _public(address):
    return (
        address.is_global and not address.is_multicast and not address.is_reserved
        and not address.is_loopback and not address.is_link_local
        and not address.is_unspecified
        and not (isinstance(address, ipaddress.IPv6Address) and (
            address.ipv4_mapped or address.sixtofour or address.teredo
            or address in ipaddress.ip_network("64:ff9b::/96")
        ))
    )


def _resolve_public(host: str, port: int) -> str:
    try:
        answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [ipaddress.ip_address(answer[4][0]) for answer in answers]
        if not addresses or not all(_public(address) for address in addresses):
            raise _invalid()
        return str(addresses[0])
    except (OSError, ValueError):
        raise _invalid() from None


async def validate_user_llm_endpoint(base_url: str) -> str:
    endpoint = normalize_user_llm_endpoint(base_url)
    url = httpx.URL(endpoint)
    try:
        await asyncio.wait_for(asyncio.to_thread(_resolve_public, url.host, url.port or (443 if url.scheme == "https" else 80)), 5)
    except TimeoutError:
        raise _invalid() from None
    return endpoint


def _pinned_request(request: httpx.Request, address: str) -> httpx.Request:
    headers = request.headers.copy()
    headers["host"] = request.url.netloc.decode("ascii")
    extensions = dict(request.extensions)
    extensions["sni_hostname"] = request.url.host
    return httpx.Request(
        request.method, request.url.copy_with(host=address), headers=headers,
        stream=request.stream, extensions=extensions,
    )


class PublicHTTPTransport(httpx.BaseTransport):
    def __init__(self):
        self._transport = httpx.HTTPTransport(trust_env=False, retries=0)

    def handle_request(self, request):
        normalize_user_llm_endpoint(str(request.url))
        address = _resolve_public(request.url.host, request.url.port or (443 if request.url.scheme == "https" else 80))
        response = self._transport.handle_request(_pinned_request(request, address))
        if 300 <= response.status_code < 400:
            response.close()
            raise _invalid()
        return response

    def close(self):
        self._transport.close()


class PublicAsyncHTTPTransport(httpx.AsyncBaseTransport):
    def __init__(self):
        self._transport = httpx.AsyncHTTPTransport(trust_env=False, retries=0)

    async def handle_async_request(self, request):
        normalize_user_llm_endpoint(str(request.url))
        try:
            address = await asyncio.wait_for(asyncio.to_thread(_resolve_public, request.url.host, request.url.port or (443 if request.url.scheme == "https" else 80)), 5)
        except TimeoutError:
            raise _invalid() from None
        response = await self._transport.handle_async_request(_pinned_request(request, address))
        if 300 <= response.status_code < 400:
            await response.aclose()
            raise _invalid()
        return response

    async def aclose(self):
        await self._transport.aclose()


def create_user_llm_http_client(**kwargs) -> httpx.Client:
    kwargs.setdefault("timeout", 15)
    return httpx.Client(**{**kwargs, "transport": PublicHTTPTransport(), "follow_redirects": False, "trust_env": False})


def create_user_llm_async_http_client(**kwargs) -> httpx.AsyncClient:
    kwargs.setdefault("timeout", 15)
    return httpx.AsyncClient(**{**kwargs, "transport": PublicAsyncHTTPTransport(), "follow_redirects": False, "trust_env": False})
