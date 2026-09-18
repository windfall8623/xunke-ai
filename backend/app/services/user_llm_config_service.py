"""Personal credentials for learners; current administrators use system models."""
from __future__ import annotations

import asyncio
import json

from app.core.config import get_settings
from app.core.db import execute, fetch_one, transaction
from app.core.errors import AppError, conflict
from app.core.user_llm_crypto import api_key_hint, decrypt_api_key, encrypt_api_key
from app.llm.configuration import LLMConfig, resolve_llm_config
from app.llm.user_endpoint import create_user_llm_async_http_client, normalize_user_llm_endpoint
from app.models.user_llm_config import LLMConfigRequest, LLMConfigView


def configuration_required():
    return AppError(422, "llm_configuration_required", "请先在个人中心配置自有模型后再使用 AI 功能")


async def get_user_llm_config(owner_id: int, *, conn=None):
    return await fetch_one(
        "SELECT provider,model,base_url,api_key_cipher FROM user_llm_configs WHERE owner_id=%s",
        (owner_id,), conn=conn,
    )


async def get_actor_role(owner_id: int, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT role FROM users WHERE id=%s"
        + (" FOR UPDATE" if lock else " FOR SHARE" if conn is not None else ""),
        (owner_id,), conn=conn,
    )
    if not row:
        raise AppError(401, "unauthorized", "请先登录")
    return row["role"]


def _stored_config(row, owner_id, settings):
    return LLMConfig(provider=row["provider"], model=row["model"],
                     base_url=normalize_user_llm_endpoint(row["base_url"]),
                     api_key=decrypt_api_key(row["api_key_cipher"], owner_id, settings), source="user")


async def resolve_actor_llm_config(owner_id: int, settings=None, *, conn=None) -> LLMConfig:
    """Re-read DB role; no DNS/network or cached authorization while locks are held."""
    settings = settings or get_settings()
    role = await get_actor_role(owner_id, conn=conn)
    if role == "admin":
        return resolve_llm_config(settings)
    row = await get_user_llm_config(owner_id, conn=conn)
    if row:
        return _stored_config(row, owner_id, settings)
    raise configuration_required()


async def get_my_llm_config(owner_id: int, settings=None) -> LLMConfigView:
    settings = settings or get_settings()
    role = await get_actor_role(owner_id)
    row = await get_user_llm_config(owner_id)
    can_use_system = role == "admin"
    if row and not can_use_system:
        # Metadata remains readable even after losing the encryption secret;
        # it must never cause a silent fallback to system credentials.
        try:
            hint = api_key_hint(decrypt_api_key(row["api_key_cipher"], owner_id, settings))
        except AppError:
            hint = None
        return LLMConfigView(configured=True, provider=row["provider"], model=row["model"],
                             base_url=row["base_url"], api_key_hint=hint,
                             can_use_system=False, source="user")
    system = resolve_llm_config(settings) if can_use_system else None
    return LLMConfigView(
        configured=False, provider=system.provider if system else None,
        model=system.model or None if system else None,
        base_url=system.base_url or None if system else None,
        api_key_hint=None, can_use_system=can_use_system,
        source="system" if system else None,
    )


async def save_my_llm_config(owner_id: int, body: LLMConfigRequest, settings=None) -> LLMConfigView:
    settings = settings or get_settings()
    role = await get_actor_role(owner_id)
    if role == "admin":
        raise AppError(403, "system_llm_managed", "管理员账户使用平台配置的系统模型")
    try:
        endpoint = normalize_user_llm_endpoint(body.base_url)
        config = LLMConfig(provider=body.provider, model=body.model, base_url=endpoint,
                           api_key=body.api_key or "", source="user")
    except ValueError:
        raise AppError(422, "invalid_llm_endpoint", "请填写模型 API 根地址") from None
    previous = await get_user_llm_config(owner_id)
    if body.api_key is None:
        if not previous or (previous["provider"], previous["model"], previous["base_url"]) != (config.provider, config.model, config.base_url):
            raise AppError(422, "api_key_required", "新增或更换配置时必须填写 API Key")
        config = _stored_config(previous, owner_id, settings)
    if not config.configured:
        raise AppError(422, "api_key_required", "请填写有效的 API Key")
    # Fail closed on deployment crypto errors BEFORE making a billable probe.
    cipher = encrypt_api_key(config.api_key, owner_id, settings)
    await probe_provider(config)
    async with transaction() as conn:
        current_role = await get_actor_role(owner_id, conn=conn, lock=True)
        if current_role == "admin":
            raise AppError(403, "system_llm_managed", "管理员账户使用平台配置的系统模型")
        current = await get_user_llm_config(owner_id, conn=conn)
        if current != previous:
            raise conflict("llm_configuration_changed", "模型配置已更新或移除，请重新加载后再保存")
        await execute(
            "INSERT INTO user_llm_configs(owner_id,provider,model,base_url,api_key_cipher) "
            "VALUES(%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
            "provider=VALUES(provider),model=VALUES(model),base_url=VALUES(base_url),"
            "api_key_cipher=VALUES(api_key_cipher),updated_at=UTC_TIMESTAMP(6)",
            (owner_id, config.provider, config.model, config.base_url, cipher),
            conn=conn,
        )
    return LLMConfigView(configured=True, provider=config.provider, model=config.model,
                         base_url=config.base_url, api_key_hint=api_key_hint(config.api_key),
                         can_use_system=False, source="user")


async def delete_my_llm_config(owner_id: int):
    async with transaction() as conn:
        await get_actor_role(owner_id, conn=conn, lock=True)
        await execute("DELETE FROM user_llm_configs WHERE owner_id=%s", (owner_id,), conn=conn)


async def probe_provider(config: LLMConfig) -> None:
    """One non-streaming chat, no retries, 8 output tokens, 15s total, 64KiB response."""
    import httpx
    from app.llm.provider_errors import user_provider_failure

    native = config.provider == "anthropic"
    url = config.base_url + ("/v1/messages" if native else "/chat/completions")
    headers = ({"x-api-key": config.api_key, "anthropic-version": "2023-06-01"}
               if native else {"Authorization": f"Bearer {config.api_key}"})
    payload = {"model": config.model, "max_tokens": 8, "stream": False,
               "messages": [{"role": "user", "content": "Reply OK."}]}
    try:
        async with asyncio.timeout(15):
            async with create_user_llm_async_http_client() as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > 65536:
                            raise AppError(422, "user_llm_failed", "模型探测响应过大，请检查 API 地址")
                    response._content = bytes(content)
                    response.raise_for_status()
                    data = json.loads(content)
                    if not isinstance(data, dict) or not data.get("content" if native else "choices"):
                        raise AppError(422, "user_llm_failed", "模型未返回有效聊天响应，请检查 API 地址")
    except AppError:
        raise
    except Exception as error:
        if isinstance(error, TimeoutError):
            error = httpx.ReadTimeout("Probe deadline exceeded")
        failure = user_provider_failure(error, api_key=config.api_key)
        raise failure or AppError(422, "user_llm_failed", "自有模型探测失败，请检查配置") from None
