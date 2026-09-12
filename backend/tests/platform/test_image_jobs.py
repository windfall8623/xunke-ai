import pytest

from tests.platform.test_assets import png_bytes
from tests.platform.test_learning import saved_quiz  # noqa: F401


@pytest.mark.asyncio
async def test_images_are_durable_partial_and_never_regenerated_on_retry(saved_quiz):
    from app.core.db import fetch_one
    from app.services import job_service, provider_meter
    from app.services.image_job_service import run_images

    api, session, quiz_id = saved_quiz
    owner = session["user"]["id"]
    calls = []

    async def provider(question):
        calls.append(question["id"])
        if question["id"] == "q2":
            raise TimeoutError("injected model timeout")
        return png_bytes()

    for key in ("images:first", "images:network-retry"):
        job = await job_service.enqueue_job(owner, "images", {"quiz_id": quiz_id}, key)
        job = await job_service.claim_job("test-images", task_id=job["task_id"])
        with provider_meter.execution(job):
            await run_images(job, provider=provider)
        persisted = await fetch_one(
            "SELECT status FROM quiz_tasks WHERE task_id=%s", (job["task_id"],)
        )
        assert persisted["status"] == "completed"
    assert calls == ["q1", "q2", "q3"]
    detail = (await api.get("/api/v1/user/quizzes/" + quiz_id)).json()["data"]
    assert detail["images_status"] == "partial"
    assert detail["questions"][1]["image_status"] == "unknown"
    assert (await api.get(detail["questions"][0]["image_url"])).status_code == 200
    count = await fetch_one(
        "SELECT COUNT(*) AS n FROM image_generation_logs WHERE quiz_id=%s", (quiz_id,)
    )
    assert count["n"] == 2
    assert (await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,)))[
        "total_xp"
    ] == 0


@pytest.mark.asyncio
async def test_evaluation_cannot_run_images(saved_quiz):
    from app.core.errors import AppError
    from app.services import job_service
    from app.services.image_job_service import run_images

    _, session, quiz_id = saved_quiz
    job = await job_service.enqueue_job(
        session["user"]["id"],
        "images",
        {"quiz_id": quiz_id},
        "images:eval",
        mode="evaluation",
    )
    job = await job_service.claim_job("test-images", task_id=job["task_id"])
    with pytest.raises(AppError):
        await run_images(job)


@pytest.mark.asyncio
@pytest.mark.parametrize("remote_url", [False, True])
async def test_image_commit_ack_loss_preserves_completed_operation(
    saved_quiz, monkeypatch, remote_url
):
    from contextlib import asynccontextmanager

    from app.core.db import fetch_one
    from app.services import image_job_service, job_service, provider_meter

    api, session, quiz_id = saved_quiz
    original_transaction = image_job_service.transaction
    injected = False

    @asynccontextmanager
    async def lose_first_image_commit_ack():
        nonlocal injected
        async with original_transaction() as conn:
            yield conn
        published = await fetch_one(
            "SELECT COUNT(*) AS n FROM image_operations WHERE quiz_id=%s AND status='completed'",
            (quiz_id,),
        )
        if published["n"] and not injected:
            injected = True
            raise ConnectionResetError("synthetic lost COMMIT acknowledgement")

    calls = []

    async def provider(question):
        calls.append(question["id"])
        return (
            {"image_url": "https://example.org/synthetic.png"}
            if remote_url
            else png_bytes()
        )

    async def download(url):
        assert url.startswith("https://"), (
            "Published local assets must never be downloaded as provider URLs"
        )
        return png_bytes()

    monkeypatch.setattr(image_job_service, "transaction", lose_first_image_commit_ack)
    monkeypatch.setattr(image_job_service, "download_image", download)
    for key in ("images:lost-ack", "images:replay-after-ack-loss"):
        job = await job_service.enqueue_job(
            session["user"]["id"], "images", {"quiz_id": quiz_id}, key
        )
        job = await job_service.claim_job("ack-loss-images", task_id=job["task_id"])
        with provider_meter.execution(job):
            await image_job_service.run_images(job, provider=provider)
        detail = (await api.get("/api/v1/user/quizzes/" + quiz_id)).json()["data"]
        assert detail["images_status"] == "completed"
        assert all(
            question["image_status"] == "completed" for question in detail["questions"]
        )
    assert injected and calls == ["q1", "q2", "q3"]
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM image_generation_logs WHERE quiz_id=%s",
            (quiz_id,),
        )
    )["n"] == 3


@pytest.mark.asyncio
async def test_image_redirects_meter_each_http_request(saved_quiz, monkeypatch):
    import httpx

    from app.core.db import fetch_one
    from app.rag.providers.web_evidence import SafeWebFetcher
    from app.services import image_job_service, job_service, provider_meter
    from app.workers import providers

    _, session, quiz_id = saved_quiz
    requests = []

    def handler(request):
        requests.append(str(request.url))
        hop = int(request.url.path.rsplit("/", 1)[-1])
        if hop < 3:
            return httpx.Response(302, headers={"Location": f"/image/{hop + 1}"})
        return httpx.Response(
            200, content=png_bytes(), headers={"Content-Type": "image/png"}
        )

    original_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        return original_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    async def target(self, url):
        # Address validation has its own RAG security tests. This transport has no network.
        return url, "example.org", "example.org"

    monkeypatch.setattr(SafeWebFetcher, "_target", target)
    monkeypatch.setattr(providers.httpx, "AsyncClient", fake_client)
    job = await job_service.enqueue_job(
        session["user"]["id"], "images", {"quiz_id": quiz_id}, "images:redirect-meter"
    )
    job = await job_service.claim_job("redirect-meter", task_id=job["task_id"])
    with provider_meter.execution(job):
        assert (
            await image_job_service.download_image("https://example.org/image/0")
            == png_bytes()
        )
    count = await fetch_one(
        "SELECT COUNT(*) AS n FROM provider_calls WHERE operation_id=%s AND stage='fetch'",
        (job["task_id"],),
    )
    assert count["n"] == len(requests) == 4
