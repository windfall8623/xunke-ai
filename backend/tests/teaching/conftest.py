"""Local synthetic teaching data; no live model or external document is used."""

import copy
import json

import pytest
from langchain_core.messages import AIMessage

from app.core.values import digest
from app.models.course import CourseCreate
from app.rag.budget import BudgetLedger
from app.rag.contracts import BudgetLimits, DocumentEvidence
from app.teaching.context import TeachingMaterial


@pytest.fixture
def valid_v2_course():
    return {
        "schema_version": "xunke-teach.v2", "kind": "course_draft",
        "source_policy": "topic", "status": "draft", "context": {},
        "assumptions": [], "warnings": [], "questions": [], "sources": [],
        "payload": {
            "title": "函数入门",
            "mission": {"goal": "解释函数", "prior_knowledge": [],
                        "success_criteria": ["解释函数参数与返回值"], "daily_minutes": 20},
            "course_criteria": [{
                "course_criterion_ref": "cc1", "description": "解释函数参数与返回值",
                "evidence_type": "explanation", "expectation": "使用另一组输入解释返回值如何被后续代码使用",
            }],
            "units": [{
                "unit_ref": "u1", "title": "输入与输出", "objective": "解释函数参数与返回值",
                "concepts": [], "prerequisite_unit_refs": [], "estimated_minutes": 15,
                "source_refs": [], "availability": "ready", "completion_check": "解释新函数的返回结果",
                "course_criterion_refs": ["cc1"],
            }],
        },
    }


@pytest.fixture
def valid_v2_lesson(valid_v2_course):
    unit = valid_v2_course["payload"]["units"][0]
    return {
        "schema_version": "xunke-teach.v2", "kind": "lesson_draft",
        "source_policy": "topic", "status": "draft", "context": {},
        "assumptions": [], "warnings": [], "questions": [], "sources": [],
        "payload": {
            **{key: unit[key] for key in ("unit_ref", "title", "objective", "estimated_minutes")},
            "blocks": [
                {"block_ref": "b1", "type": "explanation", "text": "参数接收输入，return 把计算结果交回调用处。",
                 "source_refs": [], "synthetic": False, "course_criterion_refs": ["cc1"]},
                {"block_ref": "b2", "type": "example", "text": "教学构造：double(3) 将参数 3 乘以 2，再返回 6。",
                 "source_refs": [], "synthetic": True, "course_criterion_refs": ["cc1"]},
                {"block_ref": "b3", "type": "recap", "text": "沿输入、计算、返回值三步追踪函数。",
                 "source_refs": [], "synthetic": False, "course_criterion_refs": ["cc1"]},
            ],
            "checks": [{"check_ref": "check1", "question_type": "short_answer",
                        "prompt": "double(5) 的返回值如何用于计算 double(5)+1？说明过程。",
                        "options": [], "course_criterion_refs": ["cc1"]}],
            "alignments": [{"course_criterion_ref": "cc1", "explanation_block_refs": ["b1"],
                            "example_block_refs": ["b2"], "check_refs": ["check1"]}],
            "next_step": "先完成自检；仍不确定时回看示例，再做本课练习。",
        },
    }


@pytest.fixture
def valid_v1_lesson(valid_v2_lesson):
    result = copy.deepcopy(valid_v2_lesson)
    result["schema_version"] = "xunke-teach.v1"
    result["payload"].pop("alignments")
    for item in [*result["payload"]["blocks"], *result["payload"]["checks"]]:
        item.pop("course_criterion_refs")
        item.pop("block_ref", None)
    return result


@pytest.fixture
def topic_spec():
    return CourseCreate(topic="函数", goal="解释函数", lesson_count=1, preload_first_lesson=False)


@pytest.fixture
def teaching_budget():
    return BudgetLedger(BudgetLimits(max_llm_calls=5, max_output_tokens=12000))


@pytest.fixture
def strict_material():
    text = "本地合成测试材料：参数接收输入，return 把结果交回调用处。"
    artifact_hash = digest(text)
    evidence = DocumentEvidence(
        evidence_id="fixture-e1", owner_id=7, namespace="production", title="本地合成测试材料",
        excerpt=text, text_hash=artifact_hash, doc_id="fixture-doc", document_version_id="fixture-v1", parse_artifact_id="fixture-p1",
        index_build_id="fixture-build", attempt_id="fixture-attempt", chunk_id="fixture-chunk",
        locator={"source_sha256": artifact_hash, "parse_artifact_id": "fixture-p1",
                 "canonical_text_hash": artifact_hash, "parser_version": "fixture-v1",
                 "normalizer_version": "fixture-v1", "block_id": "fixture-block",
                 "start_char": 0, "end_char": len(text), "quote_hash": artifact_hash, "paragraph": 1},
    )
    return TeachingMaterial(evidence={"s1": evidence})


class ScriptedChat:
    """Replace only the provider transport, keeping validation and budgets real."""

    def __init__(self, *replies):
        self.replies = iter(replies)
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(list(messages))
        reply = next(self.replies)
        if isinstance(reply, BaseException):
            raise reply
        return reply


def reply(raw, *, output_tokens=100, **kwargs):
    content = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    usage = None if output_tokens is None else {
        "input_tokens": 40, "output_tokens": output_tokens, "total_tokens": 40 + output_tokens,
    }
    return AIMessage(content=content, usage_metadata=usage, **kwargs)
