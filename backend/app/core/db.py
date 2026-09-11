"""Connection management only. Deployment migrations are explicit and resumable."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import aiomysql

from app.core.config import get_settings

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
        try:
            yield conn
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


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
