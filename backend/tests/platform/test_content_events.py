import uuid

import pytest
from langchain_core.messages import AIMessageChunk, HumanMessage

from app.core.db import execute, fetch_all, fetch_one
from app.core.errors import AppError
from app.core.values import load
from app.services import content_event_service as content, job_service, provider_meter
from tests.platform.test_course_preload import make_course, make_unit


@pytest.mark.asyncio
async def test_stream_is_one_provider_call_with_cumulative_usage(learner, platform_settings):
    _, session = learner
    job = await job_service.enqueue_job(session["user"]["id"], "quiz", {"user_input": "usage", "question_count": 3}, uuid.uuid4().hex)
    job = await job_service.claim_job("content-meter", task_id=job["task_id"])
    platform_settings.llm_input_cny_per_million = 1
    platform_settings.llm_output_cny_per_million = 1
    observed = []

    class StreamModel:
        calls = 0

        async def astream(self, messages):
            self.calls += 1
            yield AIMessageChunk(content='{"answer":"first', usage_metadata={"input_tokens": 8, "output_tokens": 2, "total_tokens": 10})
            assert observed == ['{"answer":"first']  # visible while the paid call is still running
            yield AIMessageChunk(content=' second"}', usage_metadata={"input_tokens": 8, "output_tokens": 6, "total_tokens": 14}, response_metadata={"finish_reason": "stop"})

        async def ainvoke(self, messages):
            raise AssertionError("A stream must not be followed by another paid call")

    model = StreamModel()
    with provider_meter.execution(job):
        answer = await provider_meter.MeteredChat(model).ainvoke_streamed([HumanMessage(content="example")], on_chunk=lambda chunk: observed.append(chunk.content))
    rows = await fetch_all("SELECT status,usage_json FROM provider_calls WHERE operation_id=%s", (job["task_id"],))
    assert model.calls == len(rows) == 1
    assert answer.content == '{"answer":"first second"}'
    usage = load(rows[0]["usage_json"])
    assert rows[0]["status"] == "completed"
    assert (usage["input_tokens"], usage["output_tokens"]) == (8, 6)


@pytest.mark.asyncio
async def test_preview_revision_replay_lease_and_publication(learner, platform_settings):
    from app.services.content_event_stream import content_events_endpoint
    from app.rag.contracts import ActorContext

    api, session = learner
    owner = session["user"]["id"]
    platform_settings.content_events_enabled = True
    course, scope, lessons = await make_course(owner, [make_unit("流式课程")])
    job = await job_service.enqueue_job(owner, "course_lesson", {"course_id": course, "lesson_id": lessons[0]}, uuid.uuid4().hex, scope=scope)
    job = await job_service.claim_job("preview-test", task_id=job["task_id"])
    await execute("UPDATE learning_course_lessons SET active_task_id=%s,generation_task_id=%s,status='generating' WHERE lesson_id=%s", (job["task_id"], job["task_id"], lessons[0]))
    await content.append_content_frame(job, 1, "block", {"validated_blocks": [{"block_id": "b1", "text": "old", "source_refs": []}]})
    await content.append_content_frame(job, 2, "reset", {"reason": "new_draft"})
    await content.append_content_frame(job, 2, "block", {"validated_blocks": [{"block_id": "b2", "text": "new", "source_refs": []}]})
    assert await content.read_content(owner, job["task_id"], job["attempt"], 1) == []
    replay = await content.read_content(owner, job["task_id"], job["attempt"], 2)
    assert [frame["type"] for frame in replay] == ["reset", "block"]
    assert replay[1]["payload"]["validated_blocks"][0]["text"] == "new"
    assert await content.read_content(owner + 99999, job["task_id"], job["attempt"], 2) == []
    with pytest.raises(AppError) as forbidden:
        await content_events_endpoint(None, actor=ActorContext(owner_id=owner + 99999), kind="course", task_id=job["task_id"])
    assert forbidden.value.status == 404
    with pytest.raises(AppError):
        await content.append_content_frame({**job, "attempt": job["attempt"] + 1}, 2, "delta", {"text": "stale worker"})
    await job_service.complete_job(job, {})
    assert (await content.read_content(owner, job["task_id"], job["attempt"], 2))[-1]["type"] == "finalized"
    assert (await fetch_one("SELECT content_version FROM learning_course_lessons WHERE lesson_id=%s", (lessons[0],)))["content_version"] == 0


@pytest.mark.asyncio
async def test_failed_or_truncated_stream_never_replays_automatically(learner, platform_settings):
    _, session = learner
    job = await job_service.enqueue_job(session["user"]["id"], "quiz", {"user_input": "timeout", "question_count": 3}, uuid.uuid4().hex)
    job = await job_service.claim_job("content-timeout", task_id=job["task_id"])

    class BrokenStream:
        async def astream(self, messages):
            yield AIMessageChunk(content='{"answer":"partial')
            raise TimeoutError("mock interrupted provider")

        async def ainvoke(self, messages):
            raise AssertionError("No automatic second model call")

    with provider_meter.execution(job), pytest.raises(TimeoutError):
        await provider_meter.MeteredChat(BrokenStream()).ainvoke_streamed([], on_chunk=lambda chunk: None)
    rows = await fetch_all("SELECT status FROM provider_calls WHERE operation_id=%s", (job["task_id"],))
    assert len(rows) == 1 and rows[0]["status"] == "unknown"
