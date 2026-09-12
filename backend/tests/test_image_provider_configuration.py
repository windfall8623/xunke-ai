from types import SimpleNamespace

import httpx
import pytest

from app.core.config import Settings


BLOCKED = [
    {"dashscope_base_url": "https://api.siliconflow.cn/v1"},
    {
        "dashscope_base_url": "https://api.siliconflow.cn/v1",
        "dashscope_image_api_key": "independent-image-fixture",
    },
    {
        "dashscope_base_url": "https://api.siliconflow.cn/v1",
        "dashscope_image_base_url": "https://dashscope.aliyuncs.com/api/v1",
    },
    {
        "dashscope_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "dashscope_image_base_url": "https://images.example.test/api/v1",
    },
    {
        "dashscope_base_url": "https://dashscope.aliyuncs.com.example.test/compatible-mode/v1"
    },
]

ALLOWED = [
    (
        {"dashscope_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"},
        "https://dashscope.aliyuncs.com/api/v1",
        "embedding-fixture-key",
    ),
    (
        {
            "dashscope_base_url": "https://tenant.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/"
        },
        "https://tenant.cn-beijing.maas.aliyuncs.com/api/v1",
        "embedding-fixture-key",
    ),
    (
        {
            "dashscope_base_url": "https://api.siliconflow.cn/v1",
            "dashscope_image_api_key": "independent-image-fixture",
            "dashscope_image_base_url": "https://images.example.test/native/api/v1/",
        },
        "https://images.example.test/native/api/v1",
        "independent-image-fixture",
    ),
    (
        {
            "dashscope_base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "dashscope_image_api_key": "independent-image-fixture",
        },
        "https://dashscope-intl.aliyuncs.com/api/v1",
        "independent-image-fixture",
    ),
]


def configured_settings(overrides, tmp_path):
    return Settings(
        _env_file=None,
        **{
            "data_dir": str(tmp_path),
            "dashscope_api_key": "embedding-fixture-key",
            "dashscope_embedding_model": "Qwen/Qwen3-Embedding-8B",
            "dashscope_image_api_key": "",
            "dashscope_image_base_url": "",
            **overrides,
        },
    )


@pytest.fixture
def image_transports(monkeypatch):
    import dashscope

    from app.services import image_job_service

    calls = []
    image_url = "https://image.example.test/fixture.png"
    client_type = httpx.AsyncClient

    def respond(request):
        calls.append((str(request.url), request.headers["authorization"]))
        return httpx.Response(
            200,
            json={
                "output": {
                    "choices": [{"message": {"content": [{"image": image_url}]}}]
                }
            },
        )

    def client(**kwargs):
        return client_type(transport=httpx.MockTransport(respond), **kwargs)

    def sdk_call(**kwargs):
        calls.append((dashscope.base_http_api_url, "Bearer " + kwargs["api_key"]))
        return SimpleNamespace(
            status_code=200,
            output=SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=[{"image": image_url}])
                    )
                ]
            ),
        )

    monkeypatch.setattr(image_job_service.httpx, "AsyncClient", client)
    monkeypatch.setattr(dashscope, "base_http_api_url", "https://fixture.invalid")
    monkeypatch.setattr(dashscope.MultiModalConversation, "call", sdk_call)
    return calls, image_url


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", BLOCKED)
@pytest.mark.parametrize("entrypoint", ["durable", "legacy"])
async def test_image_credentials_are_not_reused_across_providers(
    monkeypatch, tmp_path, image_transports, overrides, entrypoint
):
    from app.core.errors import AppError
    from app.services import image_job_service, image_service

    settings = configured_settings(overrides, tmp_path)
    monkeypatch.setattr(image_job_service, "get_settings", lambda: settings)
    monkeypatch.setattr(image_service, "get_settings", lambda: settings)
    calls, _ = image_transports
    with pytest.raises(AppError) as caught:
        if entrypoint == "durable":
            await image_job_service.generate_image({"stem": "fixture"})
        else:
            image_service._call_image_model_sync("fixture")
    assert caught.value.code == "image_provider_unavailable"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides,base,key", ALLOWED)
@pytest.mark.parametrize("entrypoint", ["durable", "legacy"])
async def test_official_fallback_and_explicit_image_gateway_use_expected_credentials(
    monkeypatch, tmp_path, image_transports, overrides, base, key, entrypoint
):
    from app.services import image_job_service, image_service

    settings = configured_settings(overrides, tmp_path)
    monkeypatch.setattr(image_job_service, "get_settings", lambda: settings)
    monkeypatch.setattr(image_service, "get_settings", lambda: settings)
    calls, image_url = image_transports
    if entrypoint == "durable":
        assert await image_job_service.generate_image({"stem": "fixture"}) == {
            "image_url": image_url
        }
        expected_url = base + "/services/aigc/multimodal-generation/generation"
    else:
        assert image_service._call_image_model_sync("fixture") == image_url
        expected_url = base
    assert calls == [(expected_url, "Bearer " + key)]
