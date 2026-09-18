"""Validated lesson blocks reach the private preview; publication stays atomic.

The provider transport is scripted and preview storage is replaced by an in-memory
head, so no model call, database or HTTP endpoint takes part in these checks.
"""

import copy
import json

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from app.core.values import digest
from app.rag.budget import BudgetLedger
from app.services import content_event_service
from app.teaching.context import TeachingMaterial
from app.teaching.contracts_v2 import CourseDraftV2
from app.teaching.generator import CourseGenerator
from app.teaching.policy import freeze_teaching_policy
from app.teaching.review_contracts import TeachingAgentInput, TeachingAgentPorts
from tests.teaching.conftest import reply
from tests.teaching.test_agents_graph import blocking_proposal
from tests.teaching.test_review_policy import passing_proposal


class _Chunks:
    """Only a provider transport: real chunk filtering and aggregation still run."""

    def __init__(self, items):
        self.items = items

    async def astream(self, messages):
        for item in self.items:
            if isinstance(item, BaseException):
                raise item
            yield item


class ScriptedStreamChat:
    """A scripted reply is either a chunk list (streamed) or one complete message."""

    def __init__(self, *replies):
        self.replies = iter(replies)
        self.calls = []
        self.streamed = 0

    def _next(self, messages):
        self.calls.append(list(messages))
        reply_value = next(self.replies)
        if isinstance(reply_value, BaseException):
            raise reply_value
        return reply_value

    async def ainvoke(self, messages):
        value = self._next(messages)
        if isinstance(value, list):
            from app.llm.streaming import collect_stream

            return await collect_stream(_Chunks(value), messages, None)
        return value

    async def ainvoke_streamed(self, messages, *, on_chunk):
        from app.llm.streaming import collect_stream

        value = self._next(messages)
        self.streamed += 1
        chunks = value if isinstance(value, list) else [value]
        return await collect_stream(_Chunks(chunks), messages, on_chunk)


def stream_chunks(draft, *, splits=("\"block_ref\": \"b2\"", "\"block_ref\": \"b3\"")):
    """Cut one JSON document so blocks complete in separate provider chunks."""
    raw = json.dumps(draft, ensure_ascii=False)
    cuts = [raw.index(marker) for marker in splits if marker in raw]
    pieces, start = [], 0
    for cut in cuts:
        pieces.append(raw[start:cut])
        start = cut
    pieces.append(raw[start:])
    return [
        AIMessageChunk(
            content=piece,
            usage_metadata={"input_tokens": 40, "output_tokens": 25 * (index + 1),
                            "total_tokens": 40 + 25 * (index + 1)},
        )
        for index, piece in enumerate(pieces)
    ]


class FakeContentStore:
    """Reproduce the frame protocol of append_content_frame without storage."""

    def __init__(self, *, broken=False):
        self.frames = []
        self.broken = broken
        self.head = None

    async def append(self, job, generation_revision, frame_type, payload):
        if self.broken:
            raise RuntimeError("preview storage unavailable")
        clean = content_event_service.ContentPayload.model_validate(payload)
        if self.head is None:
            self.head = {"generation_revision": generation_revision, "seq": 0}
        elif generation_revision > self.head["generation_revision"]:
            if frame_type != "reset":
                raise ValueError("A new draft requires a reset before its blocks")
            self.frames = [frame for frame in self.frames if frame["generation_revision"] != self.head["generation_revision"]]
            self.head = {"generation_revision": generation_revision, "seq": 0}
        elif generation_revision != self.head["generation_revision"]:
            from app.core.errors import conflict

            raise conflict("preview_revision_changed", "内容草稿已更新")
        if frame_type == "reset":
            self.frames = [frame for frame in self.frames if frame["generation_revision"] != generation_revision]
        self.head["seq"] += 1
        frame = {"task_id": job["task_id"], "generation_revision": generation_revision,
                 "seq": self.head["seq"], "type": frame_type,
                 "payload": clean.model_dump(mode="json", exclude_none=True)}
        encoded = json.dumps(frame, ensure_ascii=False)
        if len(encoded.encode("utf-8")) > content_event_service.MAX_FRAME_BYTES:
            raise ValueError("Content frame exceeds preview limit")
        self.frames.append(frame)
        return frame

    def blocks(self):
        return [block["block_id"] for frame in self.frames if frame["type"] == "block"
                for block in frame["payload"]["validated_blocks"]]

    def types(self):
        return [frame["type"] for frame in self.frames]


@pytest.fixture
def preview(monkeypatch):
    """Install a live ContentPreview for a claimed production course_lesson job."""
    store = FakeContentStore()
    job = {"task_id": "task_lesson_preview", "kind": "course_lesson", "mode": "production",
           "attempt": 1, "user_id": 7}

    def install(*, broken=False):
        store.broken = broken
        monkeypatch.setattr(content_event_service, "append_content_frame", store.append)
        # Each test coroutine runs in its own copied context, so this cannot leak.
        preview_object = content_event_service.ContentPreview(job)
        content_event_service._preview.set(preview_object)
        return preview_object

    return store, install


def input_for(course, spec, material=None):
    payload = CourseDraftV2.model_validate(course).payload
    return TeachingAgentInput(
        kind="lesson", spec=spec, unit=payload.units[0], course_criteria=tuple(payload.course_criteria),
        material=material or TeachingMaterial(), plan_hash=digest("saved-plan"), criteria_revision=1,
        scope_fingerprint=digest("topic-scope"), frozen_plan=payload.model_dump(mode="json"),
    )


def ports_for(chat, policy):
    from app.teaching.agents import PlannerAgent, ReviewerAgent, TeacherAgent
    from app.teaching.reviewer import TeachingReviewer

    generator = CourseGenerator(chat, chat, reviewer=TeachingReviewer(chat))
    claims = []

    async def authorize():
        return None

    async def claim(stage, *, candidate_hash):
        assert stage not in claims, "a durable slot cannot be replayed"
        claims.append(stage)

    async def noop(_value):
        return None

    ports = TeachingAgentPorts(
        planner=PlannerAgent(generator, policy), teacher=TeacherAgent(generator, policy),
        reviewer=ReviewerAgent(generator.reviewer, policy), authorize=authorize,
        claim_stage=claim, heartbeat=noop, checkpoint=noop, record_summary=lambda summary: None,
    )
    return ports, claims


@pytest.mark.asyncio
async def test_guided_lesson_streams_checked_blocks_in_order(valid_v2_course, valid_v2_lesson, topic_spec, preview):
    """A learner reads finished paragraphs while the teaching review still runs."""
    from app.teaching.graph import run_teaching_graph

    store, install = preview
    install()
    policy = freeze_teaching_policy("lesson", "guided", False, "topic")
    budget = BudgetLedger(policy.budget_limits(300))
    chat = ScriptedStreamChat(stream_chunks(valid_v2_lesson), reply(passing_proposal()))
    ports, claims = ports_for(chat, policy)
    result = await run_teaching_graph(input_for(valid_v2_course, topic_spec), policy, ports, budget=budget, run_id="fixture")
    assert result["terminal_reason"] == "completed"
    assert claims == ["initial", "review_initial"]
    assert chat.streamed == 1 and budget.snapshot().llm_calls == 2
    assert store.blocks() == ["b1", "b2", "b3"]
    assert store.types() == ["block", "block", "block"]
    first = store.frames[0]["payload"]
    assert first["validation"] == "structure_and_references_checked"
    assert first["validated_blocks"][0]["text"] == valid_v2_lesson["payload"]["blocks"][0]["text"]
    # Blocks appear before the report exists, but nothing else does.
    assert all(frame["generation_revision"] == 1 for frame in store.frames)
    body = json.dumps(store.frames, ensure_ascii=False)
    for secret in ("check_ref", "alignments", "next_step", "double(5)"):
        assert secret not in body


@pytest.mark.asyncio
async def test_repair_resets_the_preview_and_drops_first_draft_blocks(valid_v2_course, valid_v2_lesson, topic_spec, preview):
    """The shared repair slot raises the revision; the earlier draft cannot survive."""
    from app.teaching.graph import run_teaching_graph

    store, install = preview
    install()
    revised = copy.deepcopy(valid_v2_lesson)
    revised["payload"]["blocks"][1]["text"] += "返回值由调用处接收。"
    policy = freeze_teaching_policy("lesson", "guided", False, "topic")
    budget = BudgetLedger(policy.budget_limits(300))
    chat = ScriptedStreamChat(
        stream_chunks(valid_v2_lesson), reply(blocking_proposal()),
        stream_chunks(revised), reply(passing_proposal()),
    )
    ports, claims = ports_for(chat, policy)
    result = await run_teaching_graph(input_for(valid_v2_course, topic_spec), policy, ports, budget=budget, run_id="fixture")
    assert claims == ["initial", "review_initial", "repair", "review_recheck"]
    assert result["terminal_reason"] == "completed" and result["generation_revision"] == 2
    assert store.types() == ["reset", "block", "block", "block"]
    assert store.frames[0]["payload"]["reason"] == "new_draft"
    assert store.blocks() == ["b1", "b2", "b3"]
    assert all(frame["generation_revision"] == 2 for frame in store.frames)
    kept = [block["text"] for frame in store.frames if frame["type"] == "block"
            for block in frame["payload"]["validated_blocks"]]
    assert revised["payload"]["blocks"][1]["text"] in kept
    assert valid_v2_lesson["payload"]["blocks"][1]["text"] not in kept


@pytest.mark.asyncio
async def test_preview_write_failure_does_not_fail_generation(valid_v2_course, valid_v2_lesson, topic_spec, preview):
    """Losing the preview channel closes it; the lesson is still generated once."""
    from app.teaching.graph import run_teaching_graph

    store, install = preview
    live = install(broken=True)
    policy = freeze_teaching_policy("lesson", "guided", False, "topic")
    budget = BudgetLedger(policy.budget_limits(300))
    chat = ScriptedStreamChat(stream_chunks(valid_v2_lesson), reply(passing_proposal()))
    ports, claims = ports_for(chat, policy)
    result = await run_teaching_graph(input_for(valid_v2_course, topic_spec), policy, ports, budget=budget, run_id="fixture")
    assert result["terminal_reason"] == "completed"
    assert result["candidate"]["draft"]["payload"]["blocks"][0]["text"] == valid_v2_lesson["payload"]["blocks"][0]["text"]
    assert claims == ["initial", "review_initial"] and budget.snapshot().llm_calls == 2
    assert store.frames == [] and live.disabled is True


@pytest.mark.asyncio
async def test_block_outside_current_evidence_is_withheld_but_not_published(valid_v2_course, valid_v2_lesson, topic_spec, preview, teaching_budget):
    """A block citing evidence outside this draft never previews, and none publishes."""
    from app.teaching.quality import TeachingDraftInvalid

    store, install = preview
    live = install()
    course = CourseDraftV2.model_validate(valid_v2_course).payload
    draft = copy.deepcopy(valid_v2_lesson)
    draft["payload"]["blocks"][1]["source_refs"] = ["s9"]
    chat = ScriptedStreamChat(AIMessage(
        content=json.dumps(draft, ensure_ascii=False),
        usage_metadata={"input_tokens": 40, "output_tokens": 120, "total_tokens": 160},
    ))
    with pytest.raises(TeachingDraftInvalid):
        # topic drafts cannot claim sources, so publication is refused as before.
        await CourseGenerator(chat, chat).generate_once(
            "lesson", topic_spec, TeachingMaterial(), unit=course.units[0],
            course_criteria=course.course_criteria, budget=teaching_budget,
        )
    assert store.blocks() == ["b1", "b3"] and live.disabled is False
    assert "s9" not in json.dumps(store.frames, ensure_ascii=False)


@pytest.mark.asyncio
async def test_oversized_block_is_skipped_without_closing_the_preview(valid_v2_course, valid_v2_lesson, topic_spec, preview, teaching_budget):
    store, install = preview
    live = install()
    course = CourseDraftV2.model_validate(valid_v2_course).payload
    draft = copy.deepcopy(valid_v2_lesson)
    draft["payload"]["blocks"][0]["text"] = "参" * 4000
    chat = ScriptedStreamChat(AIMessage(
        content=json.dumps(draft, ensure_ascii=False),
        usage_metadata={"input_tokens": 40, "output_tokens": 200, "total_tokens": 240},
    ))
    result = await CourseGenerator(chat, chat).generate_once(
        "lesson", topic_spec, TeachingMaterial(), unit=course.units[0],
        course_criteria=course.course_criteria, budget=teaching_budget,
    )
    assert result["draft"]["payload"]["blocks"][0]["text"] == "参" * 4000
    assert store.blocks() == ["b2", "b3"] and live.disabled is False


@pytest.mark.asyncio
async def test_legacy_v1_lesson_has_no_previewable_block_identity(valid_v2_course, valid_v1_lesson, topic_spec, preview, teaching_budget):
    from app.teaching.contracts import TeachUnit

    store, install = preview
    install()
    raw_unit = dict(valid_v2_course["payload"]["units"][0])
    raw_unit.pop("course_criterion_refs")
    chat = ScriptedStreamChat(reply(valid_v1_lesson))
    result = await CourseGenerator(chat, chat).lesson(
        topic_spec, TeachUnit.model_validate(raw_unit), TeachingMaterial(), budget=teaching_budget,
    )
    assert result["draft"]["schema_version"] == "xunke-teach.v1"
    assert store.frames == [] and chat.streamed == 0
