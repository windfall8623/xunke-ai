import httpx
import pytest


@pytest.mark.asyncio
async def test_fetch_blocks_private_dns_and_private_redirect_before_connection():
    from app.rag.errors import RetrievalUnavailable
    from app.rag.providers.web_evidence import SafeWebFetcher

    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/secret"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        fetcher = SafeWebFetcher(client=client, resolver=lambda host: ["8.8.8.8"])
        with pytest.raises(RetrievalUnavailable):
            await fetcher.fetch("http://127.0.0.1/secret")
        assert not requests
        with pytest.raises(RetrievalUnavailable):
            await fetcher.fetch("https://public.example/start")
    assert len(requests) == 1
    assert requests[0].headers["host"] == "public.example"
    assert requests[0].url.host == "8.8.8.8"


@pytest.mark.asyncio
async def test_structured_web_evidence_uses_fetched_snapshot_not_search_summary(
    tmp_path,
):
    from app.rag.artifact_store import ArtifactStore
    from app.rag.contracts import ExecutionContext, ResolvedScope
    from app.rag.providers.web_evidence import SafeWebFetcher, WebEvidenceProvider

    queries = []

    async def search(topic, *, budget=None):
        queries.append(topic)
        return [
            {
                "url": "https://public.example/lesson",
                "title": "光合作用",
                "content": "伪造搜索摘要，不可引用",
            }
        ]

    def fetch(request):
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text="<html><h1>光合作用</h1><script>secret()</script><p>光合作用需要光😀。</p></html>",
        )

    store = ArtifactStore(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(fetch)) as client:
        provider = WebEvidenceProvider(
            search,
            SafeWebFetcher(client=client, resolver=lambda host: ["8.8.8.8"]),
            store,
        )
        evidence = await provider.retrieve(
            "批准的学习主题",
            ResolvedScope(owner_id=7, namespace="production"),
            ExecutionContext(
                mode="production", run_id="run1", storage_namespace="production"
            ),
        )
    assert queries == ["批准的学习主题"]
    assert evidence and "光合作用需要光😀。" in evidence[0].excerpt
    assert all(
        "伪造搜索摘要" not in e.excerpt and "secret()" not in e.excerpt
        for e in evidence
    )
    snapshot = store.load_web_snapshot(evidence[0].snapshot_artifact_key)
    for item in evidence:
        assert (
            snapshot["text"][item.locator.start_char : item.locator.end_char]
            == item.excerpt
        )
        assert snapshot["snapshot_hash"] == item.snapshot_hash


@pytest.mark.asyncio
async def test_fetch_rejects_oversized_snapshot():
    from app.rag.errors import RetrievalUnavailable
    from app.rag.providers.web_evidence import SafeWebFetcher

    def handler(request):
        return httpx.Response(
            200, headers={"Content-Type": "text/plain"}, text="x" * 100
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(RetrievalUnavailable):
            await SafeWebFetcher(
                client=client, resolver=lambda host: ["8.8.8.8"], max_bytes=20
            ).fetch("https://public.example/page")
