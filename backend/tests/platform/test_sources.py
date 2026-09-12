import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_point", ["response", "commit_ack"])
async def test_upload_preserves_committed_raw_when_response_is_lost(
    learner, monkeypatch, failure_point
):
    from contextlib import asynccontextmanager
    from io import BytesIO

    from starlette.datastructures import UploadFile

    from app.core.db import fetch_one
    from app.rag.contracts import ActorContext
    from app.services import source_service

    _, session = learner
    actor = ActorContext(owner_id=session["user"]["id"])
    if failure_point == "response":

        async def unavailable_view(*args, **kwargs):
            raise OSError("synthetic response failure")

        monkeypatch.setattr(source_service, "document_view", unavailable_view)
    else:
        original_transaction = source_service.transaction

        @asynccontextmanager
        async def lost_commit_ack():
            async with original_transaction() as conn:
                yield conn
            raise OSError("synthetic lost commit acknowledgement")

        monkeypatch.setattr(source_service, "transaction", lost_commit_ack)
    with pytest.raises(OSError, match="synthetic"):
        await source_service.upload_document(
            actor,
            UploadFile(BytesIO("独立合成资料。".encode()), filename="durable.txt"),
        )
    version = await fetch_one(
        "SELECT storage_key FROM kb_document_versions WHERE owner_id=%s",
        (actor.owner_id,),
    )
    assert version is not None
    assert (
        source_service.artifacts().resolve_key(version["storage_key"]).read_bytes()
        == "独立合成资料。".encode()
    )


@pytest.mark.asyncio
async def test_upload_limits_scope_and_delete_are_owner_checked(learner):
    api, session = learner
    from app.core.db import fetch_one

    r = await api.post(
        "/api/v1/knowledge/documents",
        files={
            "file": (
                "notes.txt",
                "光合作用需要光。\n叶绿素吸收光能。".encode(),
                "text/plain",
            )
        },
    )
    assert r.status_code == 202, r.text
    document = r.json()["data"]
    row = await fetch_one(
        "SELECT * FROM kb_documents WHERE doc_id=%s", (document["doc_id"],)
    )
    assert row["purpose"] == "production" and row["active_build_id"] is None
    pending = await api.post(
        "/api/v1/quiz/generate/async",
        headers={"Idempotency-Key": "pending-source"},
        json={
            "user_input": "光合作用",
            "question_count": 3,
            "doc_id": document["doc_id"],
        },
    )
    assert pending.status_code == 409
    assert (
        await api.delete("/api/v1/knowledge/documents/" + document["doc_id"])
    ).status_code == 202
    assert (
        await api.get("/api/v1/knowledge/documents/" + document["doc_id"])
    ).status_code == 404
    row = await fetch_one(
        "SELECT deleted_at,authorization_revision FROM kb_documents WHERE doc_id=%s",
        (document["doc_id"],),
    )
    assert row["deleted_at"] and row["authorization_revision"] == 2


@pytest.mark.asyncio
async def test_oversized_and_disguised_uploads_are_rejected(learner):
    api, _ = learner
    r = await api.post(
        "/api/v1/knowledge/documents",
        files={"file": ("fake.pdf", b"not a PDF", "application/pdf")},
    )
    assert r.status_code == 422
    r = await api.post(
        "/api/v1/knowledge/documents",
        files={"file": ("big.txt", b"x" * (10 * 1024 * 1024 + 1), "text/plain")},
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_eval_documents_do_not_use_production_quota(learner):
    api, session = learner
    from app.core.db import execute, fetch_one

    await execute(
        "UPDATE users SET role='evaluator' WHERE id=%s", (session["user"]["id"],)
    )
    for i in range(12):
        r = await api.post(
            "/api/v1/eval/documents",
            files={"file": (f"eval-{i}.txt", f"合成资料{i}。".encode(), "text/plain")},
        )
        assert r.status_code == 202, r.text
    prod = await api.get("/api/v1/knowledge/documents")
    assert prod.json()["data"]["total"] == 0
    count = await fetch_one(
        "SELECT COUNT(*) AS n FROM kb_documents WHERE user_id=%s AND purpose='evaluation'",
        (session["user"]["id"],),
    )
    assert count["n"] == 12


@pytest.mark.asyncio
async def test_candidate_build_late_publish_is_fenced_then_physically_cleaned(
    learner, platform_settings
):
    api, session = learner
    platform_settings.dashscope_embedding_model = "fixture-vector-v1"
    platform_settings.embedding_dimensions = 3
    from app.core.db import fetch_one
    from app.core.errors import AppError
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import ActorContext
    from app.services import job_service, source_service
    from tests.rag.helpers import FixtureEmbedding

    response = await api.post(
        "/api/v1/knowledge/documents",
        files={
            "file": (
                "source.md",
                "# 光合作用\n光合作用需要光。".encode(),
                "text/markdown",
            )
        },
    )
    doc = response.json()["data"]
    job = await job_service.claim_job("source-test", task_id=doc["task_id"])
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        candidate = await store.build(
            await source_service.build_request(job), FixtureEmbedding()
        )
        await source_service.revoke_document(
            ActorContext(owner_id=session["user"]["id"]), doc["doc_id"]
        )
        with pytest.raises(AppError):
            await source_service.publish_build(job, candidate)
        await source_service.cleanup_document(
            session["user"]["id"], doc["doc_id"], store
        )
        assert not store.projection_exists(candidate)
        assert not store.resolve_key(candidate.canonical_artifact_key).exists()
    row = await fetch_one(
        "SELECT active_build_id,status FROM kb_documents WHERE doc_id=%s",
        (doc["doc_id"],),
    )
    assert row["active_build_id"] is None and row["status"] == "deleted"


@pytest.mark.asyncio
async def test_evaluation_copy_is_idempotent_and_revoked_with_original(
    learner, platform_settings
):
    import asyncio

    from app.core.db import execute
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import ActorContext, RequestedScope
    from app.rag.engine import RagEngine
    from app.rag.errors import ScopeRevoked
    from app.services import source_service
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding

    api, session = learner
    platform_settings.dashscope_embedding_model = "fixture-vector-v1"
    platform_settings.embedding_dimensions = 3
    await execute(
        "UPDATE users SET role='evaluator' WHERE id=%s", (session["user"]["id"],)
    )
    actor = ActorContext(owner_id=session["user"]["id"], roles=["evaluator"])
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(
                store, FixtureEmbedding(), reauthorize=source_service.reauthorize_scope
            )
        )
        upload = await api.post(
            "/api/v1/knowledge/documents",
            files={"file": ("source.txt", "光合作用需要光。".encode(), "text/plain")},
        )
        source = upload.json()["data"]
        await worker.run_once(task_id=source["task_id"])
        scope = await source_service.resolve_scope(
            actor, RequestedScope(documents=[{"doc_id": source["doc_id"]}])
        )
        copies = await asyncio.gather(
            *(
                source_service.copy_for_evaluation(
                    actor, scope.documents[0], "feedback-copy"
                )
                for _ in range(2)
            )
        )
        assert copies[0]["doc_id"] == copies[1]["doc_id"]
        assert copies[0]["purpose"] == "evaluation"
        await worker.run_once(task_id=copies[0]["task_id"])
        copied_scope = await source_service.resolve_scope(
            actor,
            RequestedScope(documents=[{"doc_id": copies[0]["doc_id"]}]),
            purpose="evaluation",
        )
        assert (
            copied_scope.documents[0].canonical_text_hash
            == scope.documents[0].canonical_text_hash
        )
        assert (await source_service.list_documents(actor.owner_id))["total"] == 1
        await source_service.revoke_document(actor, source["doc_id"])
        with pytest.raises(ScopeRevoked):
            await source_service.reauthorize_scope(copied_scope)
        assert (
            await api.get("/api/v1/eval/documents/" + copies[0]["doc_id"])
        ).status_code == 404


@pytest.mark.asyncio
async def test_missing_canonical_does_not_break_document_list(
    learner, platform_settings
):
    from app.core.db import fetch_one
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.engine import RagEngine
    from app.services import source_service
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding

    api, _ = learner
    platform_settings.dashscope_embedding_model = "fixture-vector-v1"
    platform_settings.embedding_dimensions = 3
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(
                store, FixtureEmbedding(), reauthorize=source_service.reauthorize_scope
            )
        )
        upload = await api.post(
            "/api/v1/knowledge/documents",
            files={"file": ("source.txt", "光合作用需要光。".encode(), "text/plain")},
        )
        source = upload.json()["data"]
        await worker.run_once(task_id=source["task_id"])
        build = await fetch_one(
            "SELECT b.canonical_artifact_key FROM kb_index_builds b JOIN kb_documents d ON d.active_build_id=b.build_id WHERE d.doc_id=%s",
            (source["doc_id"],),
        )
        store.resolve_key(build["canonical_artifact_key"]).unlink()
        listing = await api.get("/api/v1/knowledge/documents")
        assert listing.status_code == 200
        assert listing.json()["data"]["items"][0]["status"] == "needs_reupload"
        assert (
            listing.json()["data"]["items"][0]["error_code"]
            == "source_artifact_unavailable"
        )
