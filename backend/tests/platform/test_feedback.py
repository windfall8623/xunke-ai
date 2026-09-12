"""Feedback is a reviewed draft candidate, never a generated gold label."""

import json

import pytest

from app.core.db import execute, fetch_one
from app.core.values import load
from tests.platform.test_evaluation import policy_dataset
from tests.platform.test_learning import (
    saved_quiz as saved_quiz,  # noqa: PLC0414 -- pytest fixture discovery
)


async def submit(api, quiz_id, *, consent=True):
    response = await api.post(
        f"/api/v1/quiz/{quiz_id}/feedback",
        json={
            "question_id": "q1",
            "reason": "incorrect_answer",
            "comment": "PRIVATE-REPORT-CONTACT-do-not-promote",
            "allow_evaluation_use": consent,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


async def approve(api, feedback):
    response = await api.put(
        f"/api/v1/eval/feedback/{feedback['feedback_id']}/review",
        json={
            "expected_revision": 0,
            "verdict": "approved",
            "comment": "Reviewed as candidate only",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.asyncio
async def test_feedback_is_owned_and_explicit_consent_is_required_for_promotion(
    saved_quiz,
):
    api, session, quiz_id = saved_quiz
    missing = await api.post(
        f"/api/v1/quiz/{quiz_id}/feedback",
        json={"question_id": "missing", "reason": "other"},
    )
    assert missing.status_code == 404
    feedback = await submit(api, quiz_id, consent=False)
    replay = await submit(api, quiz_id, consent=False)
    assert replay["feedback_id"] == feedback["feedback_id"]
    assert (await api.get("/api/v1/eval/feedback")).status_code == 403
    await execute(
        "UPDATE users SET role='evaluator' WHERE id=%s", (session["user"]["id"],)
    )
    reviewed = await approve(api, feedback)
    assert reviewed["revision"] == 1
    response = await api.post(
        f"/api/v1/eval/feedback/{feedback['feedback_id']}/promote",
        json={
            "expected_revision": 1,
            "name": "Candidate set",
            "redacted_request": "Practice fixture facts",
            "question_count": 3,
        },
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "evaluation_consent_required"


@pytest.mark.asyncio
async def test_feedback_promotes_a_new_draft_version_without_changing_frozen_gold(
    saved_quiz,
):
    api, session, quiz_id = saved_quiz
    await execute(
        "UPDATE users SET role='evaluator' WHERE id=%s", (session["user"]["id"],)
    )
    response = await api.post("/api/v1/eval/datasets", json=policy_dataset())
    first = response.json()["data"]
    path = f"/api/v1/eval/datasets/{first['dataset_id']}/versions/1"
    await api.post(
        path + "/samples/policy-one/review",
        json={"expected_revision": 1, "verdict": "approved"},
    )
    frozen = (await api.post(path + "/freeze", json={"expected_revision": 2})).json()[
        "data"
    ]
    feedback = await approve(api, await submit(api, quiz_id))
    payload = {
        "expected_revision": feedback["revision"],
        "dataset_id": first["dataset_id"],
        "name": "Regression candidates",
        "redacted_request": "Practice synthetic facts without identifying details",
        "question_count": 3,
    }
    endpoint = f"/api/v1/eval/feedback/{feedback['feedback_id']}/promote"
    promoted = await api.post(endpoint, json=payload)
    assert promoted.status_code == 202, promoted.text
    result = promoted.json()["data"]
    assert result["status"] == "promoted" and result["dataset_version"] == 2
    assert (await api.post(endpoint, json=payload)).json()["data"][
        "dataset_version"
    ] == 2
    assert (
        await api.post(
            endpoint, json={**payload, "redacted_request": "Changed request"}
        )
    ).status_code == 409
    old = (await api.get(path)).json()["data"]
    assert old["status"] == "frozen" and old["checksum"] == frozen["checksum"]
    draft = (
        await api.get(f"/api/v1/eval/datasets/{first['dataset_id']}/versions/2")
    ).json()["data"]
    assert draft["status"] == "draft" and len(draft["samples"]) == 2
    candidate = next(
        s for s in draft["samples"] if "feedback_regression" in s.get("tags", [])
    )
    assert (
        candidate["annotation"]["review_records"] == []
        and candidate["source_sufficient"] is False
    )
    assert "PRIVATE-REPORT-CONTACT" not in json.dumps(candidate)
    assert not candidate.get("question_rubrics")
    assert (
        await api.post(
            f"/api/v1/eval/datasets/{first['dataset_id']}/versions/2/freeze",
            json={"expected_revision": 1},
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_concurrent_promotion_replays_the_same_committed_draft(
    saved_quiz, monkeypatch
):
    import asyncio

    from app.models.feedback import FeedbackPromote
    from app.rag.contracts import ActorContext
    from app.services import feedback_service as service

    api, session, quiz_id = saved_quiz
    await execute(
        "UPDATE users SET role='evaluator' WHERE id=%s", (session["user"]["id"],)
    )
    feedback = await approve(api, await submit(api, quiz_id))
    actor = ActorContext(owner_id=session["user"]["id"], role="evaluator")
    body = FeedbackPromote(
        expected_revision=1,
        name="Concurrent candidate",
        redacted_request="Synthetic facts",
        question_count=3,
    )
    original = service.owned_feedback
    reached, release = asyncio.Event(), asyncio.Event()
    locks = 0

    async def delay_metadata_lock(*args, **kwargs):
        nonlocal locks
        if asyncio.current_task().get_name() == "slow-promotion" and kwargs.get("lock"):
            locks += 1
            if locks == 2:
                reached.set()
                await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "owned_feedback", delay_metadata_lock)
    delayed = asyncio.create_task(
        service.promote_feedback(actor, feedback["feedback_id"], body),
        name="slow-promotion",
    )
    await asyncio.wait_for(reached.wait(), 5)
    try:
        first = await service.promote_feedback(actor, feedback["feedback_id"], body)
    finally:
        release.set()
    replay = await asyncio.wait_for(delayed, 5)
    assert (
        replay["status"] == "promoted" and replay["dataset_id"] == first["dataset_id"]
    )
    assert replay["dataset_version"] == first["dataset_version"] == 1


@pytest.mark.asyncio
async def test_feedback_source_copy_and_revocation_are_real_and_isolated(
    learner, platform_settings
):
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.contracts import ValidationResult
    from app.rag.engine import RagEngine
    from app.services import source_service
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding
    from tests.rag.test_artifact_pipeline import quiz_for

    api, session = learner
    await execute(
        "UPDATE users SET role='evaluator' WHERE id=%s", (session["user"]["id"],)
    )
    platform_settings.dashscope_embedding_model = "fixture-vector-v1"
    platform_settings.embedding_dimensions = 3

    class Generator:
        async def generate(self, spec, pack, coverage, attempt, feedback=None):
            return quiz_for(spec, pack, coverage)

        async def validate_semantics(self, *args):
            return ValidationResult(passed=True, semantic_status="passed")

    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(
                store, FixtureEmbedding(), Generator(), source_service.reauthorize_scope
            )
        )
        doc = (
            await api.post(
                "/api/v1/knowledge/documents",
                files={
                    "file": ("light.txt", "光合作用需要光。".encode(), "text/plain")
                },
            )
        ).json()["data"]
        await worker.run_once(task_id=doc["task_id"])
        job = (
            await api.post(
                "/api/v1/quiz/generate/async",
                json={
                    "user_input": "光合作用",
                    "question_count": 3,
                    "doc_id": doc["doc_id"],
                },
                headers={"Idempotency-Key": "feedback-flow"},
            )
        ).json()["data"]
        await worker.run_once(task_id=job["task_id"])
        quiz = (await api.get("/api/v1/quiz/task/" + job["task_id"])).json()["data"][
            "result"
        ]
        # Fixture generator uses q1, q2, q3, identical to the production DTO.
        feedback = await approve(api, await submit(api, quiz["quiz_id"]))
        payload = {
            "expected_revision": feedback["revision"],
            "name": "Grounded regression draft",
            "redacted_request": "光合作用知识练习",
            "question_count": 3,
        }
        endpoint = f"/api/v1/eval/feedback/{feedback['feedback_id']}/promote"
        preparing = await api.post(endpoint, json=payload)
        assert preparing.status_code == 202, preparing.text
        state = preparing.json()["data"]
        assert state["status"] == "preparing" and len(state["documents"]) == 1
        assert (
            state["feedback"]["promotion"]["request"]["redacted_request"]
            == payload["redacted_request"]
        )
        copied = state["documents"][0]
        await worker.run_once(task_id=copied["task_id"])
        completed = await api.post(endpoint, json=payload)
        assert completed.status_code == 202, completed.text
        result = completed.json()["data"]
        assert result["status"] == "promoted"
        row = await fetch_one(
            "SELECT samples_json FROM eval_datasets WHERE dataset_id=%s AND version=%s",
            (result["dataset_id"], result["dataset_version"]),
        )
        candidate = load(row["samples_json"])[0]
        assert candidate["source_refs"][0]["doc_id"] == copied["doc_id"]
        assert candidate["candidate_evidence"] and not candidate.get(
            "gold_evidence_groups"
        )
        assert (await api.get("/api/v1/knowledge/documents")).json()["data"][
            "total"
        ] == 1
        await api.delete("/api/v1/knowledge/documents/" + doc["doc_id"])
        deleted = (
            await api.get(f"/api/v1/eval/datasets/{result['dataset_id']}/versions/1")
        ).json()["data"]
        assert deleted["status"] == "revoked" and deleted["samples"] == []
