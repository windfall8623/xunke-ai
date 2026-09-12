"""Restore nonempty synthetic learning/RAG data into a new database and data root.

This acceptance test uses real MySQL dump/import and real Chroma/files. It never
selects the shared yu_ai_learn_test schema or touches Docker services/volumes.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tarfile
import uuid

import aiomysql
import httpx
import pytest

from app.core import db
from app.core.audit import audit_database
from app.core.migrations import migrate, migration_status
from app.core.values import digest, dump, load
from app.rag.artifact_store import OwnerIndexStore
from app.rag.contracts import BuildResult, ValidationResult
from app.rag.engine import RagEngine
from app.services import budget_service, source_service
from app.workers.rag_owner import OwnerWorker
from tests.rag.helpers import FixtureEmbedding
from tests.rag.test_artifact_pipeline import quiz_for


class SyntheticGenerator:
    async def generate(self, spec, pack, coverage, attempt, feedback=None):
        return quiz_for(spec, pack, coverage)

    async def validate_semantics(self, *args):
        return ValidationResult(passed=True, semantic_status="passed")


async def synthetic_report(**kwargs):
    return {
        "mastered_points": ["光合作用"],
        "weak_points": [],
        "three_line_summary": ["需要光。", "能量转换。", "合成有机物。"],
        "advice": ["继续复习。"],
        "share_quote": "坚持学习。",
    }


def schema_name(role, token):
    assert role in {"src", "dst"} and re.fullmatch(r"[0-9a-f]{32}", token)
    value = f"yu_restore_{role}_{token}"
    assert re.fullmatch(r"yu_restore_(src|dst)_[0-9a-f]{32}", value)
    assert value != "yu_ai_learn_test"
    return value


def file_hashes(root):
    root = root.resolve(strict=True)
    result = {}
    for file in sorted(root.rglob("*")):
        if file.is_file():
            assert file.resolve().is_relative_to(root), (
                "Artifact escaped the test data root"
            )
            result[file.relative_to(root).as_posix()] = digest(file.read_bytes())
    return result


async def sql_fingerprints():
    tables = await db.fetch_all(
        "SELECT TABLE_NAME AS name FROM information_schema.TABLES "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
    )
    result = {}
    for row in tables:
        table = row["name"]
        assert re.fullmatch(r"[a-zA-Z0-9_]+", table)
        values = sorted(await db.fetch_all(f"SELECT * FROM `{table}`"), key=dump)
        result[table] = {"rows": len(values), "sha256": digest(dump(values))}
    return result


def mysql_command(binary, settings, schema):
    assert re.fullmatch(r"yu_restore_(src|dst)_[0-9a-f]{32}", schema)
    assert settings.mysql_host == "127.0.0.1" and settings.mysql_port == 13316
    return [
        binary,
        "--no-defaults",
        "--protocol=TCP",
        "--host=127.0.0.1",
        "--port=13316",
        "--user=root",
        "--default-character-set=utf8mb4",
    ]


def dump_sql(binary, settings, schema, path):
    command = mysql_command(binary, settings, schema) + [
        "--single-transaction",
        "--skip-lock-tables",
        "--no-tablespaces",
        "--set-gtid-purged=OFF",
        "--column-statistics=0",
        "--hex-blob",
        "--routines",
        "--triggers",
        "--events",
        f"--result-file={path}",
        schema,
    ]
    result = subprocess.run(
        command,
        env={**os.environ, "MYSQL_PWD": settings.mysql_password},
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    contents = path.read_bytes()
    assert contents and not re.search(
        rb"(?im)^\s*(?:USE\s+|(?:CREATE|DROP)\s+DATABASE\s+)", contents
    ), "Dump must not switch or replace databases"
    return digest(contents)


def restore_sql(binary, settings, schema, path):
    result = subprocess.run(
        [*mysql_command(binary, settings, schema), schema],
        input=path.read_bytes(),
        env={**os.environ, "MYSQL_PWD": settings.mysql_password},
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


def restore_files(archive_path, target_parent, workspace):
    workspace = workspace.resolve(strict=True)
    assert target_parent.resolve().is_relative_to(workspace)
    target_parent.mkdir()
    assert not list(target_parent.iterdir())
    with tarfile.open(archive_path, "r:gz") as archive:
        assert all(
            member.name == "data" or member.name.startswith("data/")
            for member in archive.getmembers()
        )
        archive.extractall(target_parent, filter="data")
    return target_parent / "data"


async def authenticated_client(api, account, *, register=False):
    if register:
        from app.services import email_verification as ev

        captured = {}

        def capture(addr, code, expires_in_seconds, settings=None):
            captured["code"] = code

        await ev.send_code(account, "testclient", transport=capture)
        body = {
            "account": account,
            "password": "Restore-Fixture-927!",
            "nickname": "恢复验收学习者🌱",
            "verification_code": captured["code"],
        }
        response = await api.post(
            "/api/v1/auth/register", json=body, headers={"Origin": "http://testserver"}
        )
    else:
        response = await api.post(
            "/api/v1/auth/login",
            json={"account": account, "password": "Restore-Fixture-927!"},
            headers={"Origin": "http://testserver"},
        )
    assert response.status_code == (201 if register else 200), response.text
    session = response.json()["data"]
    api.headers.update(
        {"X-CSRF-Token": session["csrf_token"], "Origin": "http://testserver"}
    )
    return session["user"]["id"]


async def add_document_and_quiz(api, worker, filename, content, key):
    uploaded = await api.post(
        "/api/v1/knowledge/documents",
        files={"file": (filename, content.encode(), "text/plain")},
    )
    assert uploaded.status_code == 202, uploaded.text
    document = uploaded.json()["data"]
    assert await worker.run_once(task_id=document["task_id"])
    generated = await api.post(
        "/api/v1/quiz/generate/async",
        headers={"Idempotency-Key": key},
        json={
            "user_input": "光合作用",
            "doc_id": document["doc_id"],
            "question_count": 3,
        },
    )
    assert generated.status_code == 202, generated.text
    task_id = generated.json()["data"]["task_id"]
    assert await worker.run_once(task_id=task_id)
    task = (await api.get("/api/v1/quiz/task/" + task_id)).json()["data"]
    assert task["status"] == "completed", task
    quiz = task["result"]
    reference = quiz["questions"][0]["citation_refs"][0]
    evidence = await api.get(f"/api/v1/quiz/{quiz['quiz_id']}/evidence/{reference}")
    assert evidence.status_code == 200 and evidence.json()["data"]["excerpt"] == content
    return document, quiz, reference, evidence.json()["data"]


@pytest.mark.asyncio
async def test_nonempty_backup_restore(platform_settings, tmp_path):
    # Do not depend on platform database/learner fixtures: their database is shared.
    assert db.get_mysql_pool() is None
    dump_binary, mysql_binary = shutil.which("mysqldump"), shutil.which("mysql")
    assert dump_binary and mysql_binary, (
        "Install mysql-client (mysqldump and mysql) for the restore acceptance test"
    )
    settings = platform_settings
    assert (settings.mysql_host, settings.mysql_port, settings.mysql_user) == (
        "127.0.0.1",
        13316,
        "root",
    )
    original_schema, original_root = settings.mysql_database, settings.data_dir
    token = uuid.uuid4().hex
    source_schema, target_schema = schema_name("src", token), schema_name("dst", token)
    created = []
    admin = await aiomysql.connect(
        host="127.0.0.1",
        port=13316,
        user="root",
        password=settings.mysql_password,
        autocommit=True,
        charset="utf8mb4",
    )
    try:
        async with admin.cursor() as cursor:
            for name in (source_schema, target_schema):
                # CREATE without IF NOT EXISTS prevents accidental reuse of a schema.
                await cursor.execute(
                    f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
                created.append(name)
        source_root = tmp_path / "src"
        source_root.mkdir()
        settings.mysql_database, settings.data_dir = source_schema, str(source_root)
        settings.dashscope_embedding_model = "fixture-vector-v1"
        settings.embedding_dimensions = 3
        await db.init_pool()
        await migrate()
        from app.main import app

        account = "restore_" + token[:16] + "@example.test"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as api:
            owner = await authenticated_client(api, account, register=True)
            with OwnerIndexStore(source_root, process_role="rag_owner") as store:
                worker = OwnerWorker(
                    RagEngine(
                        store,
                        FixtureEmbedding(),
                        SyntheticGenerator(),
                        source_service.reauthorize_scope,
                    ),
                    report_generator=synthetic_report,
                )
                live, quiz, reference, evidence = await add_document_and_quiz(
                    api,
                    worker,
                    "retained.txt",
                    "🌱光合作用需要光。",
                    "restorable-learning",
                )
                first = BuildResult.model_validate(
                    load(
                        (
                            await db.fetch_one(
                                "SELECT manifest_json FROM kb_index_builds WHERE doc_id=%s AND status='ready'",
                                (live["doc_id"],),
                            )
                        )["manifest_json"]
                    )
                )
                for question in quiz["questions"]:
                    answer = await api.put(
                        f"/api/v1/quiz/{quiz['quiz_id']}/answers/{question['id']}",
                        json={"selected_answers": ["A"], "duration_ms": 120},
                    )
                    assert answer.status_code == 200, answer.text
                completed = await api.post(
                    f"/api/v1/quiz/{quiz['quiz_id']}/complete",
                    json={"expected_revision": 3},
                )
                assert completed.json()["data"]["xp_awarded"] == 16
                receipt = completed.json()["data"]
                report_job = await db.fetch_one(
                    "SELECT task_id FROM quiz_tasks WHERE quiz_id=%s AND kind='report'",
                    (quiz["quiz_id"],),
                )
                assert await worker.run_once(task_id=report_job["task_id"])
                rebuilt = await api.post(
                    f"/api/v1/knowledge/documents/{live['doc_id']}/reindex",
                    json={"index_profile_id": "legacy-char-v1"},
                )
                assert rebuilt.status_code == 202, rebuilt.text
                assert await worker.run_once(task_id=rebuilt.json()["data"]["task_id"])
                active_build_id = (
                    await db.fetch_one(
                        "SELECT active_build_id FROM kb_documents WHERE doc_id=%s",
                        (live["doc_id"],),
                    )
                )["active_build_id"]
                assert active_build_id != first.index_build_id
                old_reference = await api.get(
                    f"/api/v1/quiz/{quiz['quiz_id']}/evidence/{reference}"
                )
                assert old_reference.status_code == 200
                revoked, revoked_quiz, revoked_ref, _ = await add_document_and_quiz(
                    api, worker, "revoked.txt", "光合作用需要光。", "revoked-learning"
                )
                revoked_build = BuildResult.model_validate(
                    load(
                        (
                            await db.fetch_one(
                                "SELECT manifest_json FROM kb_index_builds WHERE doc_id=%s AND status='ready'",
                                (revoked["doc_id"],),
                            )
                        )["manifest_json"]
                    )
                )
                deletion = await api.delete(
                    "/api/v1/knowledge/documents/" + revoked["doc_id"]
                )
                assert deletion.status_code == 202, deletion.text
                deletion_task = deletion.json()["data"]["task_id"]
                assert (
                    await api.get(
                        f"/api/v1/quiz/{revoked_quiz['quiz_id']}/evidence/{revoked_ref}"
                    )
                ).status_code == 404
                # Keep cleanup pending across backup, exercising durable recovery.
                assert store.projection_exists(revoked_build)
            await budget_service.reserve_budget(
                "restore-unknown", "cny", 2, [("restore-unknown-account", 5)]
            )
            await budget_service.settle_budget("restore-unknown", "cny", unknown=True)
            answers = await db.fetch_all(
                "SELECT * FROM quiz_answers WHERE quiz_id=%s ORDER BY question_id",
                (quiz["quiz_id"],),
            )
            assert len(answers) == 3 and all(row["is_correct"] for row in answers)
            before_audit = await audit_database()
            before_sql = await sql_fingerprints()
            assert before_audit["xp_total"] == 16 and before_audit["quiz_sessions"] == 2
        await db.close_mysql_pool()

        # Both owner and application writer are closed before the consistent snapshot.
        before_files = file_hashes(source_root)
        assert any(key.startswith("raw/") for key in before_files)
        assert any(key.startswith("rag/projections/") for key in before_files)
        assert any(key.startswith("rag/runs/") for key in before_files)
        sql_path, archive_path = tmp_path / "database.sql", tmp_path / "data.tar.gz"
        sql_hash = await asyncio.to_thread(
            dump_sql, dump_binary, settings, source_schema, sql_path
        )
        with tarfile.open(archive_path, "w:gz") as archive:
            archive.add(source_root, arcname="data")
        assert file_hashes(source_root) == before_files
        archive_hash = digest(archive_path.read_bytes())
        target_root = restore_files(archive_path, tmp_path / "restored", tmp_path)
        assert file_hashes(target_root) == before_files
        assert digest(sql_path.read_bytes()) == sql_hash
        await asyncio.to_thread(
            restore_sql, mysql_binary, settings, target_schema, sql_path
        )

        settings.mysql_database, settings.data_dir = target_schema, str(target_root)
        await db.init_pool()
        assert await sql_fingerprints() == before_sql
        assert await audit_database() == before_audit
        assert all(
            row["applied"] and row["checksum_matches"]
            for row in await migration_status()
        )
        assert not await db.fetch_one(
            "SELECT 1 FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_SCHEMA IS NOT NULL AND REFERENCED_TABLE_SCHEMA<>DATABASE() LIMIT 1"
        )
        assert (
            await db.fetch_all(
                "SELECT * FROM quiz_answers WHERE quiz_id=%s ORDER BY question_id",
                (quiz["quiz_id"],),
            )
            == answers
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as api:
            assert await authenticated_client(api, account) == owner
            detail = (await api.get(f"/api/v1/user/quizzes/{quiz['quiz_id']}")).json()[
                "data"
            ]
            assert detail["status"] == "settled" and len(detail["answer_records"]) == 3
            assert all(answer["is_correct"] for answer in detail["answer_records"])
            report = (await api.get(f"/api/v1/report/{quiz['quiz_id']}")).json()["data"]
            assert report["report_status"] == "completed" and report["accuracy"] == 100
            restored_evidence = await api.get(
                f"/api/v1/quiz/{quiz['quiz_id']}/evidence/{reference}"
            )
            assert (
                restored_evidence.status_code == 200
                and restored_evidence.json()["data"] == evidence
            )
            original = await api.get(
                f"/api/v1/knowledge/documents/{live['doc_id']}/source",
                params={
                    "version_id": first.document_version_id,
                    "parse_artifact_id": first.parse_artifact_id,
                    "start_char": 0,
                    "end_char": 9,
                },
            )
            assert original.status_code == 200, original.text
            assert original.json()["data"]["excerpt"] == "🌱光合作用需要光。"
            assert original.json()["data"]["locator"]["quote_hash"] == digest(
                "🌱光合作用需要光。"
            )
            again = await api.post(
                f"/api/v1/quiz/{quiz['quiz_id']}/complete",
                json={"expected_revision": 0},
            )
            assert again.json()["data"] == receipt
            assert (
                await db.fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,))
            )["total_xp"] == 16
            assert (
                await api.get("/api/v1/knowledge/documents/" + revoked["doc_id"])
            ).status_code == 404
            assert (
                await api.get(
                    f"/api/v1/quiz/{revoked_quiz['quiz_id']}/evidence/{revoked_ref}"
                )
            ).status_code == 404
            assert (
                await api.get(f"/api/v1/user/quizzes/{revoked_quiz['quiz_id']}")
            ).json()["data"]["source_status"] == "source_revoked"
            with OwnerIndexStore(target_root, process_role="rag_owner") as store:
                # Reopening actual vectors/docstores proves the copied index works
                # at its new absolute directory, including a still-pinned old build.
                assert (
                    store.read_build(first.to_source_manifest(1)).index_build_id
                    == first.index_build_id
                )
                current = BuildResult.model_validate(
                    load(
                        (
                            await db.fetch_one(
                                "SELECT manifest_json FROM kb_index_builds WHERE build_id=%s",
                                (active_build_id,),
                            )
                        )["manifest_json"]
                    )
                )
                store.read_build(current.to_source_manifest(1))
                restored_worker = OwnerWorker(
                    RagEngine(
                        store,
                        FixtureEmbedding(),
                        SyntheticGenerator(),
                        source_service.reauthorize_scope,
                    )
                )
                assert await restored_worker.run_once(task_id=deletion_task)
                assert not store.projection_exists(revoked_build)
                assert not store.resolve_key(
                    revoked_build.canonical_artifact_key
                ).exists()
                assert store.projection_exists(first) and store.projection_exists(
                    current
                )
                assert store.read_build(first.to_source_manifest(1)) == first
                assert store.read_build(current.to_source_manifest(1)) == current
            assert (
                await api.get(
                    f"/api/v1/quiz/{revoked_quiz['quiz_id']}/evidence/{revoked_ref}"
                )
            ).status_code == 404
            assert (
                await api.get(f"/api/v1/quiz/{quiz['quiz_id']}/evidence/{reference}")
            ).status_code == 200
            assert (
                await db.fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,))
            )["total_xp"] == 16
            reservation = await db.fetch_one(
                "SELECT status,actual FROM budget_reservations WHERE operation_id='restore-unknown'"
            )
            assert reservation["status"] == "unknown" and reservation["actual"] is None
        proof = {
            "fixture": "synthetic_nonempty_restore",
            "user_id": owner,
            "xp": 16,
            "answered_questions": 3,
            "quiz_sessions": 2,
            "readable_ready_builds": 2,
            "restored_pending_delete_executed": True,
            "source_span": [0, 9],
            "file_count": len(before_files),
            "sql_table_count": len(before_sql),
            "sql_sha256": sql_hash,
            "archive_sha256": archive_hash,
            "unknown_cost_preserved": True,
        }
        (tmp_path / "restore-acceptance.json").write_text(
            json.dumps(
                {
                    **proof,
                    "audit": before_audit,
                    "sql_tables": before_sql,
                    "file_hashes": before_files,
                    "source_schema": source_schema,
                    "target_schema": target_schema,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("Nonempty restore acceptance: " + json.dumps(proof))
    finally:
        await db.close_mysql_pool()
        settings.mysql_database, settings.data_dir = original_schema, original_root
        try:
            async with admin.cursor() as cursor:
                for name in reversed(created):
                    assert name in {
                        schema_name("src", token),
                        schema_name("dst", token),
                    }
                    await cursor.execute(f"DROP DATABASE `{name}`")
        finally:
            admin.close()
