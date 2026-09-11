"""Structured search plus bounded public-page snapshots, never summary citations.

URLs are checked at every redirect and requests connect to the validated IP while
preserving Host and TLS SNI. This closes the DNS re-resolution/rebinding window.
Only the approved user topic is passed to search; no retrieved private text is used.
"""

from __future__ import annotations

import asyncio
import inspect
import ipaddress
import re
import socket
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from app.rag.budget import count_tokens
from app.rag.contracts import WebEvidence, WebLocator, stable_hash, text_hash
from app.rag.errors import BudgetExceeded, RetrievalUnavailable
from app.rag.structure import _budget_spans


class _PageText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.ignored = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.ignored += 1
        if (
            tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr", "br", "section")
            and not self.ignored
        ):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            self.ignored = max(0, self.ignored - 1)
        if (
            tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "tr", "section")
            and not self.ignored
        ):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.ignored:
            self.parts.append(data)

    def text(self):
        lines = [
            re.sub(r"[\t\r \f\v]+", " ", line).strip()
            for line in "".join(self.parts).split("\n")
        ]
        return unicodedata.normalize("NFC", "\n".join(line for line in lines if line))


class SafeWebFetcher:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        resolver=None,
        max_bytes: int = 1024 * 1024,
        max_redirects: int = 3,
        timeout_seconds: float = 15,
    ):
        if (
            not 0 < max_bytes <= 2 * 1024 * 1024
            or not 0 <= max_redirects <= 5
            or not 0 < timeout_seconds <= 30
        ):
            raise ValueError("Invalid fetch limits")
        self.client, self.resolver = client, resolver
        self.max_bytes, self.max_redirects, self.timeout_seconds = (
            max_bytes,
            max_redirects,
            timeout_seconds,
        )

    async def _target(self, url: str):
        parsed = urlsplit(url)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise RetrievalUnavailable(
                "Web URL is not an allowed public HTTP(S) target"
            )
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
            if port not in (80, 443):
                raise ValueError("unapproved port")
            try:
                address = ipaddress.ip_address(parsed.hostname)
                addresses = [str(address)]
            except ValueError:
                if self.resolver is None:
                    records = await asyncio.to_thread(
                        socket.getaddrinfo,
                        parsed.hostname,
                        port,
                        type=socket.SOCK_STREAM,
                    )
                    addresses = list({record[4][0] for record in records})
                else:
                    addresses = self.resolver(parsed.hostname)
                    if inspect.isawaitable(addresses):
                        addresses = await addresses
            if not addresses or any(
                not ipaddress.ip_address(address).is_global for address in addresses
            ):
                raise ValueError("non-public target")
        except (ValueError, OSError) as exc:
            raise RetrievalUnavailable(
                "Web URL did not resolve to a permitted public address"
            ) from exc
        address = min(addresses)
        authority = f"[{address}]" if ":" in address else address
        if parsed.port:
            authority += ":" + str(port)
        pinned = urlunsplit(
            (parsed.scheme, authority, parsed.path or "/", parsed.query, "")
        )
        host_header = parsed.hostname + (
            (":" + str(parsed.port)) if parsed.port else ""
        )
        return pinned, host_header, parsed.hostname

    async def fetch(self, url: str, *, budget=None) -> dict:
        timeout = (
            min(self.timeout_seconds, budget.remaining_seconds)
            if budget
            else self.timeout_seconds
        )
        try:
            return await asyncio.wait_for(
                self._fetch(url, budget=budget), timeout=timeout
            )
        except (httpx.HTTPError, ValueError, OSError, asyncio.TimeoutError) as exc:
            raise RetrievalUnavailable("Public source fetch failed") from exc

    async def _fetch(self, url, *, budget):
        owned = self.client is None
        client = self.client or httpx.AsyncClient(
            follow_redirects=False, timeout=self.timeout_seconds, trust_env=False
        )
        current = url
        try:
            for redirect in range(self.max_redirects + 1):
                pinned, host, hostname = await self._target(current)
                if budget:
                    budget.reserve("fetch", estimated_cost_usd=0.0)
                async with client.stream(
                    "GET",
                    pinned,
                    headers={
                        "Host": host,
                        "User-Agent": "ZhixueAI-Evidence/1.0",
                        "Accept": "text/html,text/plain",
                    },
                    extensions={"sni_hostname": hostname},
                    timeout=self.timeout_seconds,
                    follow_redirects=False,
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        if redirect >= self.max_redirects or not response.headers.get(
                            "location"
                        ):
                            raise RetrievalUnavailable(
                                "Public source exceeded redirect limit"
                            )
                        current = urljoin(current, response.headers["location"])
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").lower()
                    if not content_type.startswith(
                        ("text/html", "text/plain", "application/xhtml+xml")
                    ):
                        raise RetrievalUnavailable(
                            "Web evidence source is not a text page"
                        )
                    if int(response.headers.get("content-length", 0)) > self.max_bytes:
                        raise RetrievalUnavailable("Web source exceeds the byte limit")
                    chunks, length = [], 0
                    async for chunk in response.aiter_bytes():
                        length += len(chunk)
                        if length > self.max_bytes:
                            raise RetrievalUnavailable(
                                "Web source exceeds the byte limit"
                            )
                        chunks.append(chunk)
                    body = b"".join(chunks).decode(
                        response.encoding or "utf-8", errors="replace"
                    )
                    if "html" in content_type:
                        parser = _PageText()
                        parser.feed(body)
                        text = parser.text()
                    else:
                        text = unicodedata.normalize(
                            "NFC", body.replace("\r\n", "\n").replace("\r", "\n")
                        )
                    if not text.strip():
                        raise RetrievalUnavailable("Web source contains no usable text")
                    return {
                        "url": current,
                        "text": text,
                        "raw_content_hash": text_hash(body),
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    }
            raise RetrievalUnavailable("Public source redirect limit exceeded")
        finally:
            if owned:
                await client.aclose()


class TavilySearchClient:
    def __init__(
        self, api_key: str, *, client=None, estimated_call_cost_usd: float | None = None
    ):
        if not api_key:
            raise ValueError("Search API key is required")
        self.api_key, self.client, self.estimated_call_cost_usd = (
            api_key,
            client,
            estimated_call_cost_usd,
        )

    async def __call__(self, approved_topic: str, *, budget=None):
        if budget:
            budget.reserve(
                "search",
                input_tokens=count_tokens(approved_topic),
                estimated_cost_usd=self.estimated_call_cost_usd,
            )
        owned = self.client is None
        client = self.client or httpx.AsyncClient(timeout=20, follow_redirects=False)
        try:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.api_key,
                    "query": approved_topic,
                    "max_results": 5,
                    "include_answer": False,
                    "include_raw_content": False,
                },
                timeout=min(20, budget.remaining_seconds) if budget else 20,
            )
            response.raise_for_status()
            return [
                {"url": entry["url"], "title": entry.get("title", "网页来源")}
                for entry in response.json()["results"]
            ]
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise RetrievalUnavailable(
                "Configured search provider is unavailable"
            ) from exc
        finally:
            if owned:
                await client.aclose()


class WebEvidenceProvider:
    def __init__(
        self, search, fetcher: SafeWebFetcher, artifact_store, *, max_results=5
    ):
        if not 1 <= max_results <= 5:
            raise ValueError("At most five web search results are supported")
        self.search, self.fetcher, self.artifact_store, self.max_results = (
            search,
            fetcher,
            artifact_store,
            max_results,
        )

    async def retrieve(
        self, approved_topic: str, scope, context, *, budget=None
    ) -> list[WebEvidence]:
        if not approved_topic.strip() or len(approved_topic) > 2000:
            raise ValueError("An explicit approved learning topic is required")
        topic = re.sub(r"[\x00-\x1f\x7f]", " ", approved_topic).strip()
        results = await self.search(topic, budget=budget)
        evidence, failures = [], 0
        for entry in results[: self.max_results]:
            try:
                snapshot = await self.fetcher.fetch(entry["url"], budget=budget)
            except BudgetExceeded:
                raise
            except RetrievalUnavailable:
                failures += 1
                continue
            snapshot_hash = text_hash(snapshot["text"])
            snapshot_id = (
                "web_"
                + stable_hash(
                    [
                        scope.owner_id,
                        scope.namespace,
                        snapshot["url"],
                        snapshot_hash,
                        snapshot["fetched_at"],
                        context.run_id,
                    ]
                )[:32]
            )
            snapshot.update(
                snapshot_id=snapshot_id,
                snapshot_hash=snapshot_hash,
                owner_id=scope.owner_id,
                namespace=scope.namespace,
            )
            key = self.artifact_store.save_web_snapshot(snapshot)
            for ordinal, (start, end) in enumerate(
                _budget_spans(snapshot["text"], 0, len(snapshot["text"]), 1800, 0)
            ):
                if ordinal == 3:
                    break
                excerpt = snapshot["text"][start:end]
                quote_hash = text_hash(excerpt)
                evidence.append(
                    WebEvidence(
                        evidence_id="web_ev_" + stable_hash([snapshot_id, start, end]),
                        owner_id=scope.owner_id,
                        namespace=scope.namespace,
                        title=entry.get("title", "网页来源"),
                        url=snapshot["url"],
                        fetched_at=snapshot["fetched_at"],
                        snapshot_id=snapshot_id,
                        snapshot_hash=snapshot_hash,
                        snapshot_artifact_key=key,
                        excerpt=excerpt,
                        text_hash=quote_hash,
                        locator=WebLocator(
                            block_id=snapshot_id + f":block_{ordinal + 1}",
                            start_char=start,
                            end_char=end,
                            quote_hash=quote_hash,
                        ),
                    )
                )
        if results and not evidence and failures:
            raise RetrievalUnavailable("No public source snapshot could be fetched")
        return evidence
