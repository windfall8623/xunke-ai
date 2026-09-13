"""Isolated-DB fixtures for guided course jobs: durable slots, meter and publication.

Only the provider transport is scripted. The frozen policy, the durable provider
meter, the role slot journal and the publication transaction all run for real.
"""

import json

import pytest
from langchain_core.messages import AIMessage

COURSE_TITLE = "函数入门"
UNIT_REF = "u1"
CRITERION_REF = "cc1"


def outline_draft(*, title=COURSE_TITLE, objective="解释函数参数与返回值"):
    return {
        "schema_version": "xunke-teach.v2", "kind": "course_draft", "source_policy": "topic",
        "status": "draft", "context": {}, "assumptions": [], "warnings": [], "questions": [], "sources": [],
        "payload": {
            "title": title,
            "mission": {"goal": "解释函数", "prior_knowledge": [],
                        "success_criteria": [objective], "daily_minutes": 20},
            "course_criteria": [{
                "course_criterion_ref": CRITERION_REF, "description": objective,
                "evidence_type": "explanation", "expectation": "使用另一组输入解释返回值如何被后续代码使用",
            }],
            "units": [{
                "unit_ref": UNIT_REF, "title": "输入与输出", "objective": objective,
                "concepts": [], "prerequisite_unit_refs": [], "estimated_minutes": 15,
                "source_refs": [], "availability": "ready", "completion_check": "解释新函数的返回结果",
                "course_criterion_refs": [CRITERION_REF],
            }],
        },
    }


def lesson_draft(*, example="教学构造：double(3) 将参数 3 乘以 2，再返回 6。",
                 objective="解释函数参数与返回值"):
    return {
        "schema_version": "xunke-teach.v2", "kind": "lesson_draft", "source_policy": "topic",
        "status": "draft", "context": {}, "assumptions": [], "warnings": [], "questions": [], "sources": [],
        "payload": {
            "unit_ref": UNIT_REF, "title": "输入与输出", "objective": objective, "estimated_minutes": 15,
            "blocks": [
                {"block_ref": "b1", "type": "explanation", "text": "参数接收输入，return 把计算结果交回调用处。",
                 "source_refs": [], "synthetic": False, "course_criterion_refs": [CRITERION_REF]},
                {"block_ref": "b2", "type": "example", "text": example,
                 "source_refs": [], "synthetic": True, "course_criterion_refs": [CRITERION_REF]},
                {"block_ref": "b3", "type": "recap", "text": "沿输入、计算、返回值三步追踪函数。",
                 "source_refs": [], "synthetic": False, "course_criterion_refs": [CRITERION_REF]},
            ],
            "checks": [{"check_ref": "check1", "question_type": "short_answer",
                        "prompt": "double(5) 的返回值如何用于计算 double(5)+1？说明过程。",
                        "options": [], "course_criterion_refs": [CRITERION_REF]}],
            "alignments": [{"course_criterion_ref": CRITERION_REF, "explanation_block_refs": ["b1"],
                            "example_block_refs": ["b2"], "check_refs": ["check1"]}],
            "next_step": "先完成自检；仍不确定时回看示例，再做本课练习。",
        },
    }


def passing_review(*, kind="lesson"):
    return {"dimensions": [
        {"dimension": "goal_alignment", "result": "pass"},
        {"dimension": "prerequisite_order", "result": "pass"},
        {"dimension": "example_correctness", "result": "not_applicable" if kind == "outline" else "pass"},
        {"dimension": "check_fit", "result": "pass"},
        {"dimension": "source_support", "result": "not_applicable"},
        {"dimension": "answer_leakage", "result": "pass"},
    ], "findings": []}


def blocking_review():
    result = passing_review()
    result["dimensions"][2]["result"] = "fail"
    result["findings"] = [{
        "code": "wrong_worked_example", "dimension": "example_correctness", "severity": "blocking",
        "course_criterion_refs": [CRITERION_REF], "block_refs": ["b2"],
        "explanation": "示例步骤需要修改", "suggestion": "明确输入、计算过程与返回结果",
    }]
    return result


def reply(raw, *, output_tokens=120):
    content = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    return AIMessage(content=content, usage_metadata={
        "input_tokens": 60, "output_tokens": output_tokens, "total_tokens": 60 + output_tokens,
    })


class ScriptedTeachingChat:
    """A transport only: metering, purpose caps and validation stay real.

    `disable_streaming` keeps every scripted call on the single ainvoke path so
    call accounting in a test is exact.
    """

    disable_streaming = True
    model_name = "scripted-teaching-model"

    def __init__(self, *replies):
        self.queue = list(replies)
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append([message.content for message in messages])
        if not self.queue:
            raise AssertionError("A scripted teaching provider ran out of replies")
        value = self.queue.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value


def teaching_generator(chat):
    """Wire the scripted transport exactly like app.workers.providers does."""
    from app.core.values import digest
    from app.llm.configuration import resolve_llm_config
    from app.rag.contracts import text_hash
    from app.services.provider_meter import MeteredChat
    from app.teaching.generator import CourseGenerator
    from app.teaching.reviewer import TeachingReviewer

    config = resolve_llm_config()
    identity = {"provider": config.provider, "model": config.model,
                "endpoint_hash": text_hash(config.base_url)}
    reviewer = TeachingReviewer(
        MeteredChat(chat, purpose="course_teaching_review", output_upper=1200),
        model_configuration={**identity, "temperature": 0},
    )
    assert digest  # keep the import honest for callers that hash requests
    return CourseGenerator(
        MeteredChat(chat, purpose="course_outline", output_upper=3000),
        MeteredChat(chat, purpose="course_lesson", output_upper=4500),
        model_configuration={**identity, "temperature": 0.3}, reviewer=reviewer,
    )


@pytest.fixture
def teaching_worker(platform_settings):
    """A guided-capable OwnerWorker factory sharing one owner index store."""
    from app.rag.artifact_store import OwnerIndexStore
    from app.rag.engine import RagEngine
    from app.services.source_service import reauthorize_scope
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding

    platform_settings.course_enabled = True
    platform_settings.enable_course_teaching_agents = True
    # A local placeholder key only marks the provider configured; the transport
    # below is scripted, so no request ever leaves the process.
    platform_settings.deepseek_api_key = "sk-isolated-local-test-key"
    holder = {}

    def build(chat):
        if "store" not in holder:
            store = OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner")
            store.__enter__()
            holder["store"] = store
        engine = RagEngine(holder["store"], FixtureEmbedding(), None, reauthorize_scope)
        runner = OwnerWorker(engine, course_generator=teaching_generator(chat))
        # Production deliberately redacts worker exceptions. Keep the original
        # isolated-test exception available for an actionable assertion failure.
        runner.execution_errors = []
        execute_job = runner._execute

        async def observed(job):
            try:
                return await execute_job(job)
            except BaseException as exc:
                runner.execution_errors.append(exc)
                raise

        runner._execute = observed
        return runner

    yield build
    if "store" in holder:
        holder["store"].__exit__(None, None, None)


async def guided_course(api, teaching_worker, *, key="t02-course", chat=None):
    """Announce teaching readiness, then create one guided topic course."""
    runner = teaching_worker(chat or ScriptedTeachingChat())
    await runner._worker_heartbeat()
    created = await api.post(
        "/api/v1/courses", headers={"Idempotency-Key": key},
        json={"topic": "函数", "goal": "解释函数", "lesson_count": 1,
              "preload_first_lesson": False, "teaching_mode": "guided"},
    )
    assert created.status_code == 202, created.text
    return created.json()["data"]
