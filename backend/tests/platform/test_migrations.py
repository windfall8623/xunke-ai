import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_tables", [4, 7])
async def test_four_and_seven_table_migrations_preserve_history(
    legacy_tables, platform_settings
):
    import uuid

    import aiomysql

    from app.core import db
    from app.core.audit import audit_database
    from app.core.migrations import migrate
    from app.core.values import dump

    name = "yu_migration_test_" + uuid.uuid4().hex[:12]
    server = await aiomysql.connect(
        host=platform_settings.mysql_host,
        port=platform_settings.mysql_port,
        user=platform_settings.mysql_user,
        password=platform_settings.mysql_password,
        autocommit=True,
    )
    try:
        async with server.cursor() as cur:
            await cur.execute(
                f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        platform_settings.mysql_database = name
        await db.init_pool()
        for statement in db.SCHEMA_STATEMENTS[:legacy_tables]:
            await db.execute(statement)
        owner = await db.insert(
            "INSERT INTO users(openid,nickname,total_xp) VALUES('fixture-openid','旧用户',41)"
        )
        await db.execute(
            "INSERT INTO quiz_sessions(quiz_id,user_id,title,questions_json) VALUES('legacy-quiz',%s,'旧题',%s)",
            (owner, dump([])),
        )
        await db.execute(
            "INSERT INTO answer_records(quiz_id,user_id,records_json,total_questions,correct_count,accuracy) VALUES('legacy-quiz',%s,%s,3,2,66.67)",
            (owner, dump([])),
        )
        await db.execute(
            "INSERT INTO reports(quiz_id,user_id,report_json) VALUES('legacy-quiz',%s,%s)",
            (owner, dump({"share_quote": "保留旧报告"})),
        )
        if legacy_tables == 7:
            await db.execute(
                "INSERT INTO quiz_tasks(task_id,user_id,user_input,status) VALUES('legacy-task',%s,'旧请求','running')",
                (owner,),
            )
            await db.execute(
                "INSERT INTO kb_documents(doc_id,user_id,file_name,file_type,file_size,status) VALUES('legacy-doc',%s,'old.txt','txt',100,'ready')",
                (owner,),
            )
        await migrate()
        first = await audit_database()
        await migrate()
        assert await audit_database() == first
        assert first["user_count"] == 1 and first["xp_total"] == 41
        assert (
            first["quiz_sessions"] == first["answer_records"] == first["reports"] == 1
        )
        user = await db.fetch_one(
            "SELECT id,openid,nickname,total_xp FROM users WHERE id=%s", (owner,)
        )
        assert user == {
            "id": owner,
            "openid": "fixture-openid",
            "nickname": "旧用户",
            "total_xp": 41,
        }
        if legacy_tables == 7:
            task = await db.fetch_one(
                "SELECT status,error_code FROM quiz_tasks WHERE task_id='legacy-task'"
            )
            assert task == {"status": "failed", "error_code": "legacy_unrecoverable"}
            from app.services.source_service import list_documents

            assert (await list_documents(owner))["items"][0][
                "status"
            ] == "needs_reupload"
    finally:
        await db.close_mysql_pool()
        assert name.startswith("yu_migration_test_") and len(name) == 30
        async with server.cursor() as cur:
            await cur.execute(f"DROP DATABASE `{name}`")
        server.close()


@pytest.mark.asyncio
async def test_applied_migration_checksum_changes_are_rejected(
    database, tmp_path, monkeypatch
):
    import shutil

    from app.core import migrations

    copied = tmp_path / "migration-copy"
    copied.mkdir()
    for path in migrations.MIGRATION_DIR.glob("*.sql"):
        shutil.copyfile(path, copied / path.name)
    target = copied / "000_legacy.sql"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n-- unauthorized change\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(migrations, "MIGRATION_DIR", copied)
    with pytest.raises(RuntimeError, match="checksum changed"):
        await migrations.migrate()


@pytest.mark.asyncio
async def test_pool_with_auto_init_disabled(platform_settings):
    from app.core import db

    assert hasattr(db, "init_pool"), (
        "database connection must not depend on automatic DDL"
    )
    await db.init_pool()
    try:
        assert db.get_mysql_pool() is not None
        async with db.transaction() as conn:
            row = await db.fetch_one("SELECT 1 AS connected", conn=conn)
            assert row["connected"] == 1
    finally:
        await db.close_mysql_pool()


@pytest.mark.asyncio
async def test_migration_is_repeatable_and_preserves_user(database):
    import uuid

    from app.core.db import execute, fetch_one
    from app.core.migrations import migrate, migration_status

    openid = "legacy_" + uuid.uuid4().hex
    await execute(
        "INSERT INTO users(openid,nickname,total_xp) VALUES(%s,'old',126)", (openid,)
    )
    before = await fetch_one("SELECT id,total_xp FROM users WHERE openid=%s", (openid,))
    await migrate()
    await migrate()
    after = await fetch_one("SELECT id,total_xp FROM users WHERE openid=%s", (openid,))
    assert after == before
    assert all(item["applied"] for item in await migration_status())
