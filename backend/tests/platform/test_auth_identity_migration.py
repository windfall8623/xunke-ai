import uuid

import aiomysql
import pytest


@pytest.mark.asyncio
async def test_duplicate_password_identities_block_migration_without_data_changes(
    platform_settings,
):
    from app.core import db, migrations

    database_name = "yu_auth_migration_" + uuid.uuid4().hex[:12]
    server = await aiomysql.connect(
        host=platform_settings.mysql_host,
        port=platform_settings.mysql_port,
        user=platform_settings.mysql_user,
        password=platform_settings.mysql_password,
        autocommit=True,
    )
    try:
        async with server.cursor() as cursor:
            await cursor.execute(
                f"CREATE DATABASE `{database_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        platform_settings.mysql_database = database_name
        await db.init_pool()
        await migrations.migrate(target_version="008_budget_reconciliation")
        owner = await db.insert(
            "INSERT INTO users(openid,nickname,total_xp) VALUES('fixture-old-openid','Legacy owner',19)"
        )
        for account in ("private-first-account", "private-second-account"):
            await db.execute(
                "INSERT INTO auth_identities(user_id,provider,app_scope,subject,password_hash,recovery_hash) VALUES(%s,'password','web',%s,%s,%s)",
                (owner, account, "private-password-hash", "f" * 64),
            )
        before = await db.fetch_all(
            "SELECT * FROM auth_identities ORDER BY identity_id"
        )
        for _ in range(2):
            with pytest.raises(
                RuntimeError, match="Duplicate password identities"
            ) as rejected:
                await migrations.migrate()
            message = str(rejected.value)
            assert str(owner) in message and "manual" in message.lower()
            assert "private-" not in message and "f" * 64 not in message
            assert (
                await db.fetch_all("SELECT * FROM auth_identities ORDER BY identity_id")
                == before
            )
            assert (
                await db.fetch_one(
                    "SELECT version FROM schema_migrations WHERE version='009_password_identity_unique'"
                )
                is None
            )
            assert (
                await db.fetch_one(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='auth_identities' AND column_name='password_user_id'"
                )
                is None
            )
        assert await db.fetch_one(
            "SELECT id,total_xp FROM users WHERE id=%s", (owner,)
        ) == {"id": owner, "total_xp": 19}
    finally:
        await db.close_mysql_pool()
        assert (
            database_name.startswith("yu_auth_migration_") and len(database_name) == 30
        )
        async with server.cursor() as cursor:
            await cursor.execute(f"DROP DATABASE `{database_name}`")
        server.close()
