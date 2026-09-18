"""Synthetic QA fixtures with real SQL, source ingestion, and owner execution."""

import pytest_asyncio


@pytest_asyncio.fixture
async def qa_context(learner, platform_settings):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import ActorContext
    from app.rag.engine import RagEngine
    from app.services.source_service import reauthorize_scope
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding

    api, session = learner
    platform_settings.dashscope_embedding_model = "fixture-vector-v1"
    platform_settings.embedding_dimensions = 3
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        engine = RagEngine(store, FixtureEmbedding(), reauthorize=reauthorize_scope)
        worker = OwnerWorker(engine)
        # These tests own named jobs, not the database's periodic maintenance.
        worker._next_event_purge = float("inf")
        worker._next_course_review_reconcile = float("inf")
        response = await api.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "plants.md",
                    "# 光合作用\n光合作用需要光。\n# 叶绿素\n叶绿素吸收光能。".encode(),
                    "text/markdown",
                )
            },
        )
        assert response.status_code == 202, response.text
        doc = response.json()["data"]
        assert await worker.run_once(task_id=doc["task_id"])
        ready = (await api.get("/api/v1/knowledge/documents/" + doc["doc_id"])).json()[
            "data"
        ]
        assert ready["status"] == "ready", ready
        yield dict(
            api=api,
            user=session,
            actor=ActorContext(owner_id=session["user"]["id"]),
            document=ready,
            worker=worker,
            engine=engine,
            store=store,
        )


async def new_session(context, **overrides):
    response = await context["api"].post(
        "/api/v1/qa/sessions",
        json={
            "scope": {"documents": [{"doc_id": context["document"]["doc_id"]}]},
            **overrides,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def ask(context, session, key="question-1", content="光合作用需要什么？"):
    return await context["api"].post(
        f"/api/v1/qa/sessions/{session['session_id']}/messages",
        json={"content": content, "scope_revision": session["scope_revision"]},
        headers={"Idempotency-Key": key},
    )
