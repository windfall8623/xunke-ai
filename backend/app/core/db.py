"""Connection management only. Deployment migrations are explicit and resumable."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import aiomysql

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_AFTER_COMMIT_BUDGET_SECONDS = 0.2

_pool: aiomysql.Pool | None = None
SCHEMA_STATEMENTS = [
    s.strip()
    for s in (Path(__file__).resolve().parents[2] / "migrations/000_legacy.sql")
    .read_text(encoding="utf-8")
    .split(";")
    if s.strip()
]


async def init_pool() -> None:
    global _pool
    if _pool is not None:
        return
    s = get_settings()
    _pool = await aiomysql.create_pool(
        host=s.mysql_host,
        port=s.mysql_port,
        user=s.mysql_user,
        password=s.mysql_password,
        db=s.mysql_database,
        charset="utf8mb4",
        minsize=s.mysql_pool_minsize,
        maxsize=s.mysql_pool_maxsize,
        autocommit=True,
        init_command="SET time_zone = '+00:00'",
        connect_timeout=10,
    )


async def init_mysql() -> None:
    """Explicit development bootstrap. Production uses scripts/migrate.py."""
    s = get_settings()
    conn = await aiomysql.connect(
        host=s.mysql_host,
        port=s.mysql_port,
        user=s.mysql_user,
        password=s.mysql_password,
        autocommit=True,
    )
    try:
        async with conn.cursor() as cursor:
            await cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{s.mysql_database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
    finally:
        conn.close()
    await init_pool()
    from app.core.migrations import migrate

    await migrate()


def get_mysql_pool() -> aiomysql.Pool | None:
    return _pool


def require_pool() -> aiomysql.Pool:
    if _pool is None:
        from app.core.errors import AppError

        raise AppError(503, "database_unavailable", "数据库暂不可用")
    return _pool


@asynccontextmanager
async def transaction():
    async with require_pool().acquire() as conn:
        await conn.begin()
        registry: dict[str, Callable[[], Awaitable[None]]] = {}
        conn._xunke_after_commit = registry
        committed = False
        try:
            yield conn
            await conn.commit()
            committed = True
        except BaseException:
            await conn.rollback()
            raise
        finally:
            conn._xunke_after_commit = None
            callbacks = [cb for cb in registry.values() if callable(cb)] if committed else []
    # 固定顺序：SQL 提交成功并释放连接后，才有界执行提交后通知。
    # 所有回调共享一次总预算；超时/通知失败不能反转已经提交的业务结果。
    deadline = asyncio.get_running_loop().time() + _AFTER_COMMIT_BUDGET_SECONDS
    for callback in callbacks:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            logger.warning("after_commit_callback_timeout")
            break
        try:
            # wait_for 隔离回调自己的取消；调用方任务的取消仍正常传播。
            await asyncio.wait_for(callback(), timeout=remaining)
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
            logger.warning("after_commit_callback_cancelled")
        except asyncio.TimeoutError:
            logger.warning("after_commit_callback_timeout")
            break
        except Exception:  # noqa: BLE001 - best-effort by contract
            logger.warning("after_commit_callback_failed")


def register_after_commit(conn, key: str, callback: Callable[[], Awaitable[None]]) -> None:
    """把提交后回调绑定到本次 transaction 的连接生命周期上。

    传入不受事务管理的连接（如自建连接或已退出事务的连接）时拒绝注册。
    相同 key 的回调被覆盖，用于合并同任务通知。
    """
    registry = getattr(conn, "_xunke_after_commit", None)
    if registry is None:
        raise ValueError("after-commit callbacks require an active transaction connection")
    registry[key] = callback


async def _query(sql, args=(), *, conn=None, mode="all"):
    if conn is None:
        async with require_pool().acquire() as acquired:
            return await _query(sql, args, conn=acquired, mode=mode)
    async with conn.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(sql, args)
        if mode == "execute":
            return cursor.rowcount
        if mode == "insert":
            return cursor.lastrowid
        if mode == "one":
            return await cursor.fetchone()
        return await cursor.fetchall()


async def fetch_one(sql, args=(), *, conn=None):
    return await _query(sql, args, conn=conn, mode="one")


async def fetch_all(sql, args=(), *, conn=None):
    return await _query(sql, args, conn=conn)


async def execute(sql, args=(), *, conn=None):
    return await _query(sql, args, conn=conn, mode="execute")


async def insert(sql, args=(), *, conn=None):
    return await _query(sql, args, conn=conn, mode="insert")


async def close_mysql_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
