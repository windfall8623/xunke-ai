import pytest


@pytest.mark.asyncio
async def test_real_mysql_chroma_learning_flow_report_failure_and_revocation(
    learner, platform_settings
):
    api, session = learner
    platform_settings.dashscope_embedding_model = "fixture-vector-v1"
    platform_settings.embedding_dimensions = 3
    from app.core.db import fetch_one
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import ValidationResult
    from app.rag.engine import RagEngine
    from app.services.source_service import reauthorize_scope
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding
    from tests.rag.test_artifact_pipeline import quiz_for

    class Generator:
        async def generate(self, spec, pack, coverage, attempt, feedback=None):
            return quiz_for(spec, pack, coverage)

        async def validate_semantics(self, *args):
            return ValidationResult(
                passed=True,
                semantic_status="passed",
                semantic_details={"test_fixture": True},
            )

    async def fail_report(**kwargs):
        raise RuntimeError("injected report provider failure")

    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        engine = RagEngine(store, FixtureEmbedding(), Generator(), reauthorize_scope)
        worker = OwnerWorker(engine, report_generator=fail_report)
        upload = await api.post(
            "/api/v1/knowledge/documents",
            files={"file": ("light.txt", "光合作用需要光。".encode(), "text/plain")},
        )
        assert upload.status_code == 202
        doc = upload.json()["data"]
        assert await worker.run_once(task_id=doc["task_id"])
        ready = await api.get("/api/v1/knowledge/documents/" + doc["doc_id"])
        assert ready.json()["data"]["status"] == "ready", ready.text
        create = await api.post(
            "/api/v1/quiz/generate/async",
            headers={"Idempotency-Key": "real-flow"},
            json={
                "user_input": "光合作用",
                "doc_id": doc["doc_id"],
                "question_count": 3,
            },
        )
        assert create.status_code == 202, create.text
        task = create.json()["data"]
        await worker.run_once(task_id=task["task_id"])
        response = await api.get("/api/v1/quiz/task/" + task["task_id"])
        assert response.json()["data"]["status"] == "completed", response.text
        quiz = response.json()["data"]["result"]
        assert len(quiz["questions"]) == 3 and "answer" not in quiz["questions"][0]
        ref = quiz["questions"][0]["citation_refs"][0]
        evidence = await api.get(f"/api/v1/quiz/{quiz['quiz_id']}/evidence/{ref}")
        assert evidence.json()["data"]["excerpt"] == "光合作用需要光。"
        for question in quiz["questions"]:
            r = await api.put(
                f"/api/v1/quiz/{quiz['quiz_id']}/answers/{question['id']}",
                json={"selected_answers": ["A"], "duration_ms": 120},
            )
            assert r.status_code == 200
        completion = await api.post(
            f"/api/v1/quiz/{quiz['quiz_id']}/complete", json={"expected_revision": 3}
        )
        assert completion.json()["data"]["xp_awarded"] == 16
        report = await fetch_one(
            "SELECT task_id FROM quiz_tasks WHERE quiz_id=%s AND kind='report'",
            (quiz["quiz_id"],),
        )
        await worker.run_once(task_id=report["task_id"])
        outcome = await api.get("/api/v1/report/" + quiz["quiz_id"])
        assert outcome.json()["data"]["accuracy"] == 100
        assert outcome.json()["data"]["report_status"] == "failed"
        user = await fetch_one(
            "SELECT total_xp FROM users WHERE id=%s", (session["user"]["id"],)
        )
        assert user["total_xp"] == 16
        deleted = await api.delete("/api/v1/knowledge/documents/" + doc["doc_id"])
        assert (
            await api.get(f"/api/v1/quiz/{quiz['quiz_id']}/evidence/{ref}")
        ).status_code == 404
        await worker.run_once(task_id=deleted.json()["data"]["task_id"])
        assert not store.attempts_for_document(
            owner_id=session["user"]["id"], namespace="production", doc_id=doc["doc_id"]
        )


@pytest.mark.asyncio
async def test_runtime_requires_explicit_providers_and_can_close_without_network(
    platform_settings,
):
    from app.rag.errors import RetrievalUnavailable
    from app.workers.providers import build_runtime

    runtime = build_runtime(platform_settings)
    try:
        assert runtime.engine.generator is None
        with pytest.raises(RetrievalUnavailable):
            await runtime.engine.embedding.embed_query("光合作用")
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_report_provider_cannot_replace_settled_score_with_generated_accuracy():
    import json
    from types import SimpleNamespace

    from app.workers.providers import ConfiguredReportGenerator

    captured = []

    class Model:
        async def ainvoke(self, messages):
            captured.extend(messages)
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "accuracy": 999,
                        "mastered_points": ["光合作用"],
                        "weak_points": [],
                        "three_line_summary": [
                            "需要光。",
                            "提供能量。",
                            "产生有机物。",
                        ],
                        "advice": ["继续巩固。"],
                        "share_quote": "坚持练习。",
                    },
                    ensure_ascii=False,
                )
            )

    report = await ConfiguredReportGenerator(Model())(
        topic="光合作用",
        questions=[],
        answer_records=[],
        score_summary={
            "total_questions": 3,
            "correct_count": 3,
            "accuracy": 100,
            "xp_awarded": 16,
        },
    )
    assert "accuracy" not in report.model_dump()
    assert '"accuracy": 100' in captured[-1].content
    assert report.three_line_summary == ["需要光。", "提供能量。", "产生有机物。"]


@pytest.mark.asyncio
async def test_eval_owner_executes_native_cases_and_scoring_without_learning_side_effects(
    learner, platform_settings
):
    from rag_eval.metrics import score_sample

    from app.core.db import execute, fetch_all, fetch_one
    from app.core.values import load
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import BuildResult, ValidationResult
    from app.rag.engine import RagEngine
    from app.services import evaluation_scoring
    from app.services.source_service import reauthorize_scope
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding
    from tests.rag.test_artifact_pipeline import quiz_for

    api, session = learner
    owner = session["user"]["id"]
    platform_settings.dashscope_embedding_model = "fixture-vector-v1"
    platform_settings.embedding_dimensions = 3
    await execute("UPDATE users SET role='evaluator' WHERE id=%s", (owner,))

    class Generator:
        async def generate(self, spec, pack, coverage, attempt, feedback=None):
            return quiz_for(spec, pack, coverage)

        async def validate_semantics(self, *args):
            return ValidationResult(
                passed=True,
                semantic_status="passed",
                semantic_details={"test_fixture": True},
            )

    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(store, FixtureEmbedding(), Generator(), reauthorize_scope)
        )
        upload = await api.post(
            "/api/v1/eval/documents",
            files={"file": ("eval.txt", "光合作用需要光。".encode(), "text/plain")},
        )
        assert upload.status_code == 202, upload.text
        doc = upload.json()["data"]
        await worker.run_once(task_id=doc["task_id"])
        row = await fetch_one(
            "SELECT manifest_json FROM kb_index_builds WHERE doc_id=%s AND owner_id=%s AND status='ready'",
            (doc["doc_id"], owner),
        )
        built = BuildResult.model_validate(load(row["manifest_json"]))
        source = {
            "doc_id": doc["doc_id"],
            "source_version_id": built.document_version_id,
            "parse_artifact_id": built.parse_artifact_id,
            "source_sha256": built.source_sha256,
            "canonical_text_hash": built.canonical_text_hash,
            "family_id": "fixture-family",
            "license": "synthetic_test_fixture",
            "owner_id": owner,
            "namespace": f"evaluation:{owner}",
        }
        span = {**source, **built.nodes[0].evidence.locator.model_dump(mode="json")}
        base = {
            "schema_version": "1",
            "family_ids": ["fixture-family"],
            "split": "dev",
            "source_refs": [source],
            "tags": ["synthetic"],
            "annotation": {"provenance": "test_fixture", "review_records": []},
        }
        samples = [
            {
                **base,
                "sample_id": "retrieve",
                "case_type": "retrieval",
                "query": "光合作用",
                "expected_outcome": "answerable",
                "gold_evidence_groups": [{"group_id": "g1", "alternatives": [[span]]}],
            },
            {
                **base,
                "sample_id": "quiz",
                "case_type": "quiz",
                "user_input": "光合作用",
                "question_count": 3,
                "expected_outcome": "generate",
                "source_sufficient": True,
            },
            {
                **base,
                "sample_id": "refuse",
                "case_type": "quiz",
                "user_input": "火星直径",
                "question_count": 3,
                "expected_outcome": "refuse",
                "source_sufficient": False,
            },
            {
                **base,
                "sample_id": "policy",
                "case_type": "policy",
                "expected_status": "denied",
                "expected_error_code": "forbidden",
                "harness": {
                    "synthetic_only": True,
                    "actors": [
                        {"actor_id": "alice", "synthetic": True},
                        {"actor_id": "bob", "synthetic": True},
                    ],
                    "resources": [
                        {
                            "resource_id": "copy",
                            "source_doc_id": doc["doc_id"],
                            "namespace": "evaluation",
                            "synthetic": True,
                        }
                    ],
                    "steps": [{"action": "cross_owner_read", "target": "copy"}],
                },
            },
        ]
        dataset = await api.post(
            "/api/v1/eval/datasets",
            json={
                "name": "Worker integration fixture",
                "samples": samples,
                "manifest": {
                    "state": "draft",
                    "annotation_version": "fixture-v1",
                    "sources": [source],
                    "review": {
                        "checklist": {
                            "source_rights": True,
                            "spans": True,
                            "family_split": True,
                            "answerability": True,
                            "second_review": False,
                        }
                    },
                },
            },
        )
        assert dataset.status_code == 201, dataset.text
        dataset_id = dataset.json()["data"]["dataset_id"]
        path = f"/api/v1/eval/datasets/{dataset_id}/versions/1"
        for revision, sample in enumerate(samples, 1):
            review = await api.post(
                path + f"/samples/{sample['sample_id']}/review",
                json={
                    "expected_revision": revision,
                    "verdict": "approved",
                    "comment": "Automated integration fixture",
                },
            )
            assert review.status_code == 200, review.text
        frozen = await api.post(path + "/freeze", json={"expected_revision": 5})
        assert frozen.status_code == 200, frozen.text
        created = await api.post(
            "/api/v1/eval/runs",
            headers={"Idempotency-Key": "native-flow"},
            json={
                "dataset_id": dataset_id,
                "dataset_version": 1,
                "pipeline_id": "bm25-v1",
                "repeat_count": 1,
                "max_cost_cny": 2,
            },
        )
        assert created.status_code == 202, created.text
        run_id = created.json()["data"]["run_id"]
        jobs = await fetch_all(
            "SELECT task_id FROM quiz_tasks WHERE user_id=%s AND kind='eval_sample' "
            "AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.run_id'))=%s",
            (owner, run_id),
        )
        for job in jobs:
            await worker.run_once(task_id=job["task_id"])
        rows = await fetch_all(
            "SELECT sample_id,status,prediction_status,artifact_json FROM eval_results WHERE run_id=%s",
            (run_id,),
        )
        assert {row["status"] for row in rows} == {"pending_scoring"}, rows
        assert {row["sample_id"]: row["prediction_status"] for row in rows} == {
            "retrieve": "completed",
            "quiz": "completed",
            "refuse": "refused",
            "policy": "completed",
        }
        for _ in range(4):
            claim = await evaluation_scoring.claim_scoring(
                "fixture-scorer", run_id=run_id
            )
            assert claim is not None
            metrics = score_sample(claim["sample"], claim["artifact"], claim["config"])
            await evaluation_scoring.complete_scoring(
                claim["result_id"], claim["lease_token"], claim["attempt"], metrics
            )
        result = await api.get("/api/v1/eval/runs/" + run_id)
        assert result.json()["data"]["progress"]["completed"] == 4, result.text
        assert result.json()["data"]["comparison_eligible"] is False
        deleted = await api.delete("/api/v1/eval/documents/" + doc["doc_id"])
        assert deleted.status_code == 202, deleted.text
        await execute("UPDATE users SET role='learner' WHERE id=%s", (owner,))
        await worker.run_once(task_id=deleted.json()["data"]["task_id"])
        assert not store.attempts_for_document(
            owner_id=owner, namespace=f"evaluation:{owner}", doc_id=doc["doc_id"]
        )
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM quiz_sessions WHERE user_id=%s", (owner,)
        )
    )["n"] == 0
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM image_generation_logs WHERE user_id=%s", (owner,)
        )
    )["n"] == 0
    assert (await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,)))[
        "total_xp"
    ] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancel", "replace_lease"])
async def test_late_worker_result_cannot_publish_after_cancellation_or_lease_loss(
    learner, platform_settings, change
):
    import asyncio
    from datetime import timedelta

    from app.core.db import execute, fetch_one
    from app.core.values import now
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import ValidationResult
    from app.rag.engine import RagEngine
    from app.services import job_service
    from app.services.source_service import reauthorize_scope
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding
    from tests.rag.test_artifact_pipeline import quiz_for

    api, session = learner
    owner = session["user"]["id"]
    started, release = asyncio.Event(), asyncio.Event()

    class SlowGenerator:
        async def generate(self, spec, pack, coverage, attempt, feedback=None):
            started.set()
            await release.wait()
            return quiz_for(spec, pack, coverage)

        async def validate_semantics(self, *args):
            return ValidationResult(passed=True, semantic_status="passed")

    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(store, FixtureEmbedding(), SlowGenerator(), reauthorize_scope)
        )
        response = await api.post(
            "/api/v1/quiz/generate/async",
            headers={"Idempotency-Key": "late-result"},
            json={
                "user_input": "光合作用",
                "question_count": 3,
                "source_policy": "topic",
            },
        )
        task_id = response.json()["data"]["task_id"]
        running = asyncio.create_task(worker.run_once(task_id=task_id))
        await asyncio.wait_for(started.wait(), timeout=5)
        if change == "cancel":
            await job_service.cancel_job(owner, task_id)
        else:
            await execute(
                "UPDATE quiz_tasks SET attempt=2,lease_token='replacement-lease',worker_id='replacement',lease_expires_at=%s WHERE task_id=%s",
                (now() + timedelta(seconds=60), task_id),
            )
        release.set()
        assert await asyncio.wait_for(running, timeout=10)
        job = await fetch_one(
            "SELECT status,lease_token,result_json FROM quiz_tasks WHERE task_id=%s",
            (task_id,),
        )
        assert job["result_json"] is None
        if change == "cancel":
            assert job["status"] == "cancelled"
        else:
            assert (
                job["status"] == "running" and job["lease_token"] == "replacement-lease"
            )
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM quiz_sessions WHERE user_id=%s", (owner,)
        )
    )["n"] == 0
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM rag_runs WHERE owner_id=%s", (owner,)
        )
    )["n"] == 0


@pytest.mark.asyncio
async def test_worker_reclaims_expired_lease_once_and_publishes_text_report_without_rescoring(
    learner, platform_settings
):
    from datetime import timedelta

    from app.core.db import execute, fetch_one
    from app.core.values import now
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import ValidationResult
    from app.rag.engine import RagEngine
    from app.services import job_service
    from app.services.source_service import reauthorize_scope
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding
    from tests.rag.test_artifact_pipeline import quiz_for

    api, session = learner
    owner = session["user"]["id"]

    class Generator:
        async def generate(self, spec, pack, coverage, attempt, feedback=None):
            return quiz_for(spec, pack, coverage)

        async def validate_semantics(self, *args):
            return ValidationResult(passed=True, semantic_status="passed")

    async def report(**kwargs):
        assert kwargs["score_summary"] == {
            "total_questions": 3,
            "correct_count": 3,
            "accuracy": 100,
            "xp_awarded": 16,
        }
        return {
            "accuracy": 1,
            "xp_awarded": 999,
            "mastered_points": ["光合作用"],
            "weak_points": [],
            "three_line_summary": ["需要光。", "能量转换。", "合成有机物。"],
            "advice": ["继续复习。"],
            "share_quote": "坚持学习。",
        }

    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(store, FixtureEmbedding(), Generator(), reauthorize_scope),
            report_generator=report,
        )
        created = await api.post(
            "/api/v1/quiz/generate/async",
            headers={"Idempotency-Key": "recover-lease"},
            json={
                "user_input": "光合作用",
                "question_count": 3,
                "source_policy": "topic",
            },
        )
        task_id = created.json()["data"]["task_id"]
        original = await job_service.claim_job("crashed-worker", task_id=task_id)
        await execute(
            "UPDATE quiz_tasks SET lease_expires_at=%s WHERE task_id=%s",
            (now() - timedelta(seconds=1), task_id),
        )
        assert await worker.run_once(task_id=task_id)
        assert not await worker.run_once(task_id=task_id)
        result = await api.get("/api/v1/quiz/task/" + task_id)
        quiz = result.json()["data"]["result"]
        assert quiz["quiz_id"] == original["quiz_id"]
        assert (
            await fetch_one(
                "SELECT attempt FROM quiz_tasks WHERE task_id=%s", (task_id,)
            )
        )["attempt"] == 2
        for question in quiz["questions"]:
            assert (
                await api.put(
                    f"/api/v1/quiz/{quiz['quiz_id']}/answers/{question['id']}",
                    json={"selected_answers": ["A"], "duration_ms": 1},
                )
            ).status_code == 200
        settled = await api.post(
            f"/api/v1/quiz/{quiz['quiz_id']}/complete", json={"expected_revision": 3}
        )
        assert settled.json()["data"]["xp_awarded"] == 16
        report_job = await fetch_one(
            "SELECT task_id FROM quiz_tasks WHERE quiz_id=%s AND kind='report'",
            (quiz["quiz_id"],),
        )
        await worker.run_once(task_id=report_job["task_id"])
        outcome = (await api.get("/api/v1/report/" + quiz["quiz_id"])).json()["data"]
        assert outcome["report_status"] == "completed"
        assert outcome["accuracy"] == 100 and outcome["xp_awarded"] == 16
        assert (
            "accuracy" not in outcome["report"]
            and "xp_awarded" not in outcome["report"]
        )
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM quiz_sessions WHERE user_id=%s", (owner,)
        )
    )["n"] == 1
    assert (await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,)))[
        "total_xp"
    ] == 16


@pytest.mark.asyncio
async def test_managed_heartbeat_renews_job_while_provider_waits(
    learner, platform_settings
):
    import asyncio

    from app.core.db import fetch_one
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import ValidationResult
    from app.rag.engine import RagEngine
    from app.services.source_service import reauthorize_scope
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding
    from tests.rag.test_artifact_pipeline import quiz_for

    api, _ = learner
    platform_settings.job_lease_seconds = 1
    platform_settings.job_heartbeat_seconds = 1

    class SlowGenerator:
        async def generate(self, spec, pack, coverage, attempt, feedback=None):
            await asyncio.sleep(1.3)
            return quiz_for(spec, pack, coverage)

        async def validate_semantics(self, *args):
            return ValidationResult(passed=True, semantic_status="passed")

    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(store, FixtureEmbedding(), SlowGenerator(), reauthorize_scope)
        )
        created = await api.post(
            "/api/v1/quiz/generate/async",
            headers={"Idempotency-Key": "heartbeat"},
            json={
                "user_input": "光合作用",
                "question_count": 3,
                "source_policy": "topic",
            },
        )
        task_id = created.json()["data"]["task_id"]
        assert await worker.run_once(task_id=task_id)
        row = await fetch_one(
            "SELECT status,attempt FROM quiz_tasks WHERE task_id=%s", (task_id,)
        )
        assert row == {"status": "completed", "attempt": 1}


@pytest.mark.asyncio
async def test_generated_quiz_enqueues_durable_images_and_owner_publishes_assets(
    learner, platform_settings, monkeypatch
):
    import io

    from PIL import Image

    from app.core.db import fetch_all, fetch_one
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import ValidationResult
    from app.rag.engine import RagEngine
    from app.services import image_job_service
    from app.services.source_service import reauthorize_scope
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding
    from tests.rag.test_artifact_pipeline import quiz_for

    api, session = learner
    content = io.BytesIO()
    Image.new("RGB", (160, 120), color="green").save(content, format="PNG")

    async def image_provider(question):
        return content.getvalue()

    monkeypatch.setattr(image_job_service, "generate_image", image_provider)

    class Generator:
        async def generate(self, spec, pack, coverage, attempt, feedback=None):
            return quiz_for(spec, pack, coverage)

        async def validate_semantics(self, *args):
            return ValidationResult(passed=True, semantic_status="passed")

    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(store, FixtureEmbedding(), Generator(), reauthorize_scope)
        )
        created = await api.post(
            "/api/v1/quiz/generate/async",
            headers={"Idempotency-Key": "durable-images"},
            json={
                "user_input": "光合作用",
                "question_count": 3,
                "source_policy": "topic",
                "generate_images": True,
            },
        )
        task = created.json()["data"]
        await worker.run_once(task_id=task["task_id"])
        queued = await fetch_one(
            "SELECT task_id,status FROM quiz_tasks WHERE quiz_id=%s AND kind='images'",
            (task["quiz_id"],),
        )
        assert queued["status"] == "pending"
        assert await worker.run_once(task_id=queued["task_id"])
        assert not await worker.run_once(task_id=queued["task_id"])
        detail = (await api.get("/api/v1/user/quizzes/" + task["quiz_id"])).json()[
            "data"
        ]
        assert detail["images_status"] == "completed"
        for question in detail["questions"]:
            assert question["image_status"] == "completed"
            response = await api.get(question["image_url"])
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/png"
        operations = await fetch_all(
            "SELECT status FROM image_operations WHERE quiz_id=%s", (task["quiz_id"],)
        )
        assert len(operations) == 3 and {row["status"] for row in operations} == {
            "completed"
        }
        logs = await fetch_one(
            "SELECT COUNT(*) AS n FROM image_generation_logs WHERE user_id=%s",
            (session["user"]["id"],),
        )
        assert logs["n"] == 3
