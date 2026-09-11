"""健康检查路由"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.get("/ready")
async def readiness():
    import tempfile
    from pathlib import Path

    from app.core.config import get_settings
    from app.core.db import fetch_all, fetch_one
    from app.core.migrations import migration_status
    from app.llm.configuration import resolve_llm_config
    from app.llm.image_configuration import resolve_image_config

    settings = get_settings()
    checks = {
        "database": False,
        "migrations": False,
        "storage": False,
        "rag_owner": False,
        "eval_scorer": False,
    }
    try:
        await fetch_one("SELECT 1 AS ok")
        checks["database"] = True
        migrations = await migration_status()
        checks["migrations"] = bool(migrations) and all(
            row["applied"] and row["checksum_matches"] for row in migrations
        )
        workers = await fetch_all(
            "SELECT DISTINCT role FROM worker_heartbeats WHERE heartbeat_at>UTC_TIMESTAMP(6)-INTERVAL 90 SECOND"
        )
        for row in workers:
            if row["role"] in checks:
                checks[row["role"]] = True
    except Exception:
        pass
    try:
        directory = Path(settings.data_dir)
        if directory.is_dir():
            with tempfile.TemporaryFile(dir=directory) as probe:
                probe.write(b"ready")
                probe.flush()
            checks["storage"] = True
    except OSError:
        pass
    capabilities = {
        "generation": resolve_llm_config(settings).configured,
        "embedding": bool(settings.dashscope_api_key),
        "web_search": bool(settings.enable_web_search and settings.tavily_api_key),
        "images": resolve_image_config(settings).configured,
    }
    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "checks": checks,
            "capabilities": capabilities,
        },
    )
