"""Optional images remain durable and independent of base learning."""
from unittest.mock import AsyncMock, patch

import pytest

from app.models.learning import GenerateBody
from app.services import quiz_service
from tests.test_quiz_doc_id_integration import durable_job, generation_actor  # noqa: F401 - pytest fixture registration
from tests.platform.conftest import platform_settings, database, api, learner  # noqa: F401 - pytest fixture registration
from tests.platform.test_learning import saved_quiz  # noqa: F401 - pytest fixture registration
from tests.platform.test_assets import png_bytes


@pytest.mark.asyncio
@pytest.mark.parametrize("requested", [False, True])
async def test_image_intent_is_persisted_without_calling_provider_in_http(requested, generation_actor, durable_job):
    with patch("app.services.image_job_service.generate_image",
               AsyncMock(side_effect=AssertionError("Only the owner worker may generate images"))) as image:
        task = await quiz_service.create_quiz_job(
            generation_actor,
            GenerateBody(user_input="学习水果单词", question_count=3, generate_images=requested),
            "images-intent",
        )
    assert task["status"] == "pending"
    assert durable_job.enqueue.await_args.args[2]["generate_images"] is requested
    image.assert_not_awaited()


@pytest.mark.asyncio
async def test_durable_images_are_saved_as_owned_assets_and_returned_by_quiz_api(saved_quiz):
    from app.core.db import fetch_one
    from app.services import job_service, provider_meter
    from app.services.image_job_service import run_images

    client, session, quiz_id = saved_quiz
    owner = session["user"]["id"]
    provider = AsyncMock(return_value=png_bytes())
    job = await job_service.enqueue_job(owner, "images", {"quiz_id": quiz_id}, "images-success")
    claimed = await job_service.claim_job("image-integration-test", task_id=job["task_id"])
    with provider_meter.execution(claimed):
        await run_images(claimed, provider=provider)
    detail = (await client.get("/api/v1/user/quizzes/" + quiz_id)).json()["data"]
    assert detail["images_status"] == "completed"
    assert provider.await_count == 3
    assert all(question["image_status"] == "completed" for question in detail["questions"])
    for question in detail["questions"]:
        assert question["image_url"].startswith("/api/v1/user/assets/")
        image = await client.get(question["image_url"])
        assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    count = await fetch_one("SELECT COUNT(*) AS n FROM image_generation_logs WHERE quiz_id=%s", (quiz_id,))
    assert count["n"] == 3
    assert (await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,)))["total_xp"] == 0


@pytest.mark.asyncio
async def test_all_image_provider_failures_leave_base_quiz_answerable(saved_quiz):
    from app.core.db import fetch_one
    from app.services import job_service, provider_meter
    from app.services.image_job_service import run_images

    client, session, quiz_id = saved_quiz
    provider = AsyncMock(side_effect=TimeoutError("injected ambiguous provider outcome"))
    job = await job_service.enqueue_job(session["user"]["id"], "images", {"quiz_id": quiz_id}, "images-failure")
    claimed = await job_service.claim_job("image-integration-test", task_id=job["task_id"])
    with provider_meter.execution(claimed):
        await run_images(claimed, provider=provider)
    detail = (await client.get("/api/v1/user/quizzes/" + quiz_id)).json()["data"]
    assert detail["images_status"] == "failed"
    assert len(detail["questions"]) == 3
    assert all(question["image_url"] is None for question in detail["questions"])
    assert all(question["image_status"] == "unknown" for question in detail["questions"])
    persisted = await fetch_one("SELECT status FROM quiz_tasks WHERE task_id=%s", (job["task_id"],))
    assert persisted["status"] == "completed"
    answer = await client.put(f"/api/v1/quiz/{quiz_id}/answers/q1",
                             json={"selected_answers": ["A"], "duration_ms": 100})
    assert answer.status_code == 200
    assert answer.json()["data"]["answer_record"]["is_correct"] is True
    assert provider.await_count == 3
