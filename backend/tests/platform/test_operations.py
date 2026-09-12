import pytest

from tests.test_image_provider_configuration import ALLOWED, BLOCKED


@pytest.mark.asyncio
async def test_ready_reports_database_storage_and_workers(
    api, platform_settings, tmp_path
):
    from app.core.db import execute

    await execute(
        "INSERT INTO worker_heartbeats(worker_id,role,heartbeat_at) VALUES('ready-owner','rag_owner',UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE heartbeat_at=UTC_TIMESTAMP(6)"
    )
    await execute(
        "INSERT INTO worker_heartbeats(worker_id,role,heartbeat_at) VALUES('ready-scorer','eval_scorer',UTC_TIMESTAMP(6)) ON DUPLICATE KEY UPDATE heartbeat_at=UTC_TIMESTAMP(6)"
    )
    response = await api.get("/api/v1/ready")
    assert response.status_code == 200, response.text
    assert response.json()["checks"]["migrations"]
    assert response.json()["capabilities"]["generation"] is False
    file = tmp_path / "not-a-directory"
    file.write_text("not storage")
    platform_settings.data_dir = str(file)
    response = await api.get("/api/v1/ready")
    assert response.status_code == 503 and response.json()["checks"]["storage"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides,enabled",
    [(value, False) for value in BLOCKED] + [(value, True) for value, _, _ in ALLOWED],
)
async def test_ready_reports_images_only_when_image_configuration_is_usable(
    api, platform_settings, overrides, enabled
):
    # Use the real Settings object and readiness endpoint with the isolated DB.
    for name, value in {
        "dashscope_api_key": "embedding-fixture-key",
        "dashscope_embedding_model": "Qwen/Qwen3-Embedding-8B",
        "dashscope_image_api_key": "",
        "dashscope_image_base_url": "",
        **overrides,
    }.items():
        setattr(platform_settings, name, value)
    response = await api.get("/api/v1/ready")
    payload = response.json()
    assert payload["capabilities"]["embedding"] is True
    assert payload["capabilities"]["images"] is enabled
    assert "fixture-key" not in response.text
