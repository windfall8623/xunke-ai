"""AES-GCM secrets for user-owned provider credentials only.

The encryption key is HKDF-derived from USER_LLM_KEY_SECRET, which is a
separate secret from JWT_SECRET; compromise of one never decrypts the other.
A random 12-byte nonce per write plus the owner id as AAD makes ciphertexts
non-repeating and non-transferable between owners. Plaintext keys are never
logged and never returned by any API: only a last-4 hint leaves the process.
"""

from __future__ import annotations

import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.errors import AppError

_HKDF_INFO = b"xunke/user-llm-key/v1"
_NONCE_BYTES = 12
_key_cache: dict[str, bytes] = {}


def _derive_key(settings) -> bytes:
    secret = settings.user_llm_key_secret
    if not secret or len(secret) < 32 or secret in {settings.jwt_secret, settings.email_code_secret}:
        raise AppError(
            503, "user_llm_secret_missing", "自有模型加密密钥未配置，请联系管理员"
        )
    cached = _key_cache.get(secret)
    if cached is None:
        cached = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=_HKDF_INFO,
        ).derive(secret.encode("utf-8"))
        if len(_key_cache) > 8:
            _key_cache.clear()
        _key_cache[secret] = cached
    return cached


def _aad(owner_id: int) -> bytes:
    return str(owner_id).encode("ascii")


def encrypt_api_key(plaintext: str, owner_id: int, settings=None) -> str:
    import base64

    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(_derive_key(settings)).encrypt(
        nonce, plaintext.encode("utf-8"), _aad(owner_id)
    )
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_api_key(token: str, owner_id: int, settings=None) -> str:
    import base64

    if settings is None:
        from app.core.config import get_settings

        settings = get_settings()
    key = _derive_key(settings)
    try:
        raw = base64.b64decode(token.encode("ascii"), altchars=b"-_", validate=True)
        plaintext = AESGCM(key).decrypt(
            raw[:_NONCE_BYTES], raw[_NONCE_BYTES:], _aad(owner_id)
        )
        return plaintext.decode("utf-8")
    except Exception:
        # Invalid base64, wrong key version or foreign owner are indistinguishable.
        raise AppError(
            422, "user_llm_key_unreadable", "自有模型密钥无法解密，请重新保存配置"
        ) from None


def api_key_hint(plaintext: str) -> str | None:
    return f"****{plaintext[-4:]}" if len(plaintext) >= 4 else None
