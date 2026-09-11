"""Owner-scoped local media; decode and re-encode before publishing an asset."""

import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.db import execute, fetch_one, transaction
from app.core.errors import AppError, not_found
from app.core.values import uid
from app.services.source_service import artifacts


def normalize_image(raw: bytes, *, max_pixels=16_000_000) -> bytes:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as probe:
                if (
                    probe.format not in ("PNG", "JPEG", "WEBP")
                    or probe.width * probe.height > max_pixels
                ):
                    raise ValueError("Unsupported image")
                probe.verify()
            with Image.open(io.BytesIO(raw)) as image:
                image = ImageOps.exif_transpose(image)
                image.thumbnail((1024, 1024))
                clean = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                output = io.BytesIO()
                clean.save(output, format="PNG", optimize=True)
                return output.getvalue()
    except (
        ValueError,
        OSError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise AppError(
            422, "invalid_image", "请上传有效的 PNG、JPEG 或 WebP 图片"
        ) from exc


async def save_avatar(owner, file):
    raw = bytearray()
    limit = 2 * 1024 * 1024
    while chunk := await file.read(min(65536, limit + 1 - len(raw))):
        raw.extend(chunk)
        if len(raw) > limit:
            raise AppError(413, "avatar_too_large", "头像不能超过 2MB")
    import asyncio

    encoded = await asyncio.to_thread(normalize_image, bytes(raw))
    asset_id = uid("asset")
    key = f"assets/{asset_id}.png"
    path = artifacts().resolve_key(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    url = "/api/v1/user/assets/" + asset_id
    try:
        async with transaction() as conn:
            await execute(
                "INSERT INTO user_assets(asset_id,owner_id,storage_key,content_type) VALUES(%s,%s,%s,%s)",
                (asset_id, owner, key, "image/png"),
                conn=conn,
            )
            await execute(
                "UPDATE users SET avatar_url=%s WHERE id=%s", (url, owner), conn=conn
            )
    except BaseException:
        try:
            published = await fetch_one(
                "SELECT asset_id FROM user_assets WHERE asset_id=%s", (asset_id,)
            )
            if published is None:
                path.unlink(missing_ok=True)
        except BaseException:
            pass  # Unknown COMMIT outcome: retain the file for the owner sweep.
        raise
    return {"avatar_url": url}


async def read_asset(owner, asset_id):
    row = await fetch_one(
        "SELECT storage_key,content_type,source_scope_json FROM user_assets WHERE asset_id=%s AND owner_id=%s",
        (asset_id, owner),
    )
    if not row:
        raise not_found()
    if row["source_scope_json"]:
        from app.core.values import load
        from app.services.source_service import reauthorize_scope

        await reauthorize_scope(load(row["source_scope_json"]))
    path = artifacts().resolve_key(row["storage_key"])
    if not path.is_file():
        raise not_found()
    return path, row["content_type"]
