"""The DashScope compatibility endpoint receives strings and explicit floats."""

import json

import httpx
import pytest


@pytest.mark.asyncio
async def test_explicit_embedding_batches_strings_and_dimensions():
    from app.rag.providers.embedding_adapter import DashScopeEmbedding

    requests = []

    def handle(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert (
            request.url
            == "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"
        )
        assert all(isinstance(x, str) for x in payload["input"])
        assert payload["encoding_format"] == "float"
        assert payload["dimensions"] == 3
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": i, "embedding": [1.0, 0.0, 0.5]}
                    for i, _ in enumerate(payload["input"])
                ],
                "usage": {"total_tokens": 12},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = DashScopeEmbedding(
            api_key="explicit-test-key",
            model="text-embedding-v4",
            dimensions=3,
            client=client,
        )
        result = await adapter.embed_documents(["段落 " + str(i) for i in range(23)])
    assert len(result) == 23
    assert [len(r["input"]) for r in requests] == [10, 10, 3]
    assert all(r["model"] == "text-embedding-v4" for r in requests)


@pytest.mark.asyncio
async def test_embedding_rejects_wrong_dimensions_without_retry():
    from app.rag.errors import RetrievalUnavailable
    from app.rag.providers.embedding_adapter import DashScopeEmbedding

    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        adapter = DashScopeEmbedding(
            api_key="explicit-test-key", dimensions=3, client=client
        )
        with pytest.raises(RetrievalUnavailable):
            await adapter.embed_query("hello")
    assert len(requests) == 1


def test_embedding_requires_explicit_credentials_and_rejects_foreign_endpoint():
    from app.rag.providers.embedding_adapter import DashScopeEmbedding

    with pytest.raises(ValueError):
        DashScopeEmbedding(api_key="")
    with pytest.raises(ValueError):
        DashScopeEmbedding(api_key="x", base_url="http://127.0.0.1:8000/v1")
