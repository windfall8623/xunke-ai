"""Shared isolated-DB fixtures for the course completion check and text application.

A published course, its goal identities and a scripted (never live) quiz/teaching
provider. Authorization boundaries stay in test_course_assessment_authorization.py.
"""

import pytest
from app.core.db import execute
from app.core.values import dump, uid
from app.rag.contracts import ResolvedScope, ValidationResult, stable_hash

LESSON_VERSION = 1


def unit_for(ref, title, objective, criterion_refs, *, availability="available"):
    return {
        "unit_ref": ref, "title": title, "objective": objective,
        "estimated_minutes": 10, "availability": availability,
        "course_criterion_refs": list(criterion_refs),
    }


def content_for(objective):
    return {"payload": {"objective": objective, "blocks": [
        {"type": "explanation", "text": f"{objective}：先看输入，再看返回值。", "source_refs": []},
        {"type": "recap", "text": "按输入、计算、返回值三步复述。", "source_refs": []},
    ]}, "sources": [], "warnings": []}


def criterion_definition(ref, description, evidence_type, expectation, lesson_ids):
    """Mirror publish_course_criteria's frozen definition identity exactly."""
    return dict(
        description=description, expectation=expectation, evidence_type=evidence_type,
        lesson_ids=sorted(lesson_ids),
        requirements=dict(evidence_type=evidence_type, all_mapped_items=True, minimum_items=1,
                          independent_help="declared_none_without_recorded_hints"),
        origin="generated_v2",
    )


async def published_course(owner, criteria, *, source_policy="topic"):
    """Insert one ready course whose goals already carry stable identities.

    `criteria` items are (ref, description, evidence_type, lesson_title, lesson_status).
    A `material_gap` lesson keeps its goal visible but unavailable for a check.
    """
    scope = ResolvedScope(owner_id=owner, namespace="production")
    course_id, outline_task = uid("course"), uid("task")
    await execute(
        "INSERT INTO quiz_tasks(task_id,user_id,status,kind,operation,mode,user_input,request_json) "
        "VALUES(%s,%s,'completed','course_outline','course.outline','production','',%s)",
        (outline_task, owner, dump({"course_id": course_id})),
    )
    spec = dict(topic="函数", goal="解释与运用函数", prior_knowledge="", daily_minutes=20,
                timezone="Asia/Shanghai", lesson_count=len(criteria), preload_first_lesson=False,
                source_policy=source_policy, scope=None, teaching_mode="fast", request_quality_review=False)
    await execute(
        "INSERT INTO learning_courses(course_id,owner_id,spec_json,source_policy,requested_scope_json,"
        "resolved_scope_json,scope_fingerprint,creation_task_id,outline_task_id,status,outline_json,"
        "revision,criteria_revision) VALUES(%s,%s,%s,%s,NULL,%s,%s,%s,%s,'ready',%s,2,1)",
        (course_id, owner, dump(spec), source_policy, dump(scope), scope.fingerprint,
         outline_task, outline_task,
         dump({"schema_version": "xunke-teach.v2", "payload": {"title": "函数入门", "mission": None},
               "sources": [], "warnings": []})),
    )
    goals = {}
    for position, (ref, description, evidence_type, title, status) in enumerate(criteria):
        lesson_id = uid("lesson")
        await execute(
            "INSERT INTO learning_course_lessons(lesson_id,course_id,owner_id,unit_ref,position,"
            "unit_json,content_json,status,revision,content_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,2,%s)",
            (lesson_id, course_id, owner, "u" + ref, position,
             dump(unit_for("u" + ref, title, description, [ref],
                           availability="material_gap" if status == "material_gap" else "available")),
             dump(content_for(description)) if status == "ready" else None, status,
             LESSON_VERSION if status == "ready" else 0),
        )
        expectation = f"换一组输入说明{description}"
        frozen = criterion_definition(ref, description, evidence_type, expectation, [lesson_id])
        criterion_id = uid("ccrit")
        await execute(
            "INSERT INTO learning_course_criteria(course_criterion_id,criteria_revision,course_id,owner_id,"
            "course_criterion_ref,position,description,evidence_type,expectation,definition_hash,"
            "lesson_ids_json,requirements_json,origin) VALUES(%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'generated_v2')",
            (criterion_id, course_id, owner, ref, position, description, evidence_type, expectation,
             stable_hash(frozen), dump([lesson_id]), dump(frozen["requirements"])),
        )
        goals[ref] = dict(course_criterion_id=criterion_id, lesson_id=lesson_id,
                          description=description, evidence_type=evidence_type,
                          definition_hash=stable_hash(frozen), status=status)
    return dict(course_id=course_id, scope=scope, goals=goals)


class ScriptedQuizGenerator:
    """Deterministic objective questions bound to the frozen course goals.

    Only the provider is replaced: coverage quotas, artifact schema, course
    mapping validation and publication all run as in production.
    """

    def __init__(self, *, refs_for=None, wrong_ids=()):
        self.refs_for = refs_for
        self.wrong_ids = set(wrong_ids)
        self.calls = 0

    def _refs(self, spec, target):
        if self.refs_for is not None:
            return self.refs_for(target)
        match = [item.course_criterion_ref for item in spec.course_criteria
                 if item.description == target.title]
        return match or [spec.course_criteria[0].course_criterion_ref]

    # Deterministic and clearly distinct stems: the real duplicate-question rule
    # still runs, so scripted questions must differ like generated ones do.
    STEMS = (
        "参数把调用处的哪一部分带进函数体？",
        "函数没有写 return 时，调用处收到什么？",
        "把返回值直接参与后续加法运算的前提是什么？",
        "在调用链中先执行哪一步，才可能拿到结果？",
        "改动形参名称会影响调用处的哪些代码？",
        "同一函数换一组输入后，输出通常如何变化？",
    )

    async def generate(self, spec, pack, coverage, attempt, feedback=None):
        self.calls += 1
        questions, number = [], 0
        for target in coverage.targets:
            for _ in range(target.question_quota):
                questions.append({
                    "id": f"q{number + 1}", "type": "single",
                    "stem": self.STEMS[number % len(self.STEMS)],
                    "options": [{"key": "A", "text": "正确说法"}, {"key": "B", "text": "错误说法"}],
                    "answer": ["A"], "explanation": "结业检查的独立事实。",
                    "knowledge_point": target.title, "difficulty": "easy",
                    "citation_refs": [], "coverage_target_id": target.target_id,
                    "support_quotes": [], "course_criterion_refs": self._refs(spec, target),
                })
                number += 1
        return {"title": "结业检查", "summary": "按目标组织的客观检查", "questions": questions}

    async def validate_semantics(self, *args):
        return ValidationResult(passed=True, semantic_status="passed",
                                semantic_details={"scripted_fixture": True})


def application_question(ref, criterion_refs, *, prompt):
    """A topic-policy text task: no source refs, no support quotes, private rubric."""
    return {
        "application_ref": ref, "course_criterion_refs": list(criterion_refs),
        "prompt": prompt, "response_format": "text",
        "public_expectations": ["说明输入与输出", "解释返回值的用途"],
        "source_policy": "topic", "source_refs": [], "support_quotes": [],
        "rubric": {
            "version": "course-application-rubric.v1",
            "reference_answer": "私有参考答案：先说明参数，再说明返回值如何被调用处使用。",
            "explanation": "私有评分说明，不对学习者公开。",
            "criteria": [
                {"criterion_id": "r1", "reference_point": "指出参数的作用", "weight": "0.5",
                 "evidence_refs": [], "course_criterion_refs": list(criterion_refs)},
                {"criterion_id": "r2", "reference_point": "说明返回值的用途", "weight": "0.5",
                 "evidence_refs": [], "course_criterion_refs": list(criterion_refs)},
            ],
        },
    }


def feedback_proposal(*, quotes, credits=("full", "full"), status="graded", reasons=()):
    return {
        "status": status,
        "criterion_results": [
            {"criterion_id": identity, "credit": credit,
             "rationale": f"按条目 {identity} 说明理由。", "evidence_refs": [],
             "answer_quotes": [] if credit in {"none", "uncertain"} else list(quotes)}
            for identity, credit in zip(("r1", "r2"), credits)
        ],
        "feedback": "回答已按目标维度给出教学反馈，仍需人工复核。",
        "uncertainty_reasons": list(reasons),
    }


class ScriptedApplicationGenerator:
    """Scripted transport around the real CourseApplicationGenerator contracts.

    Generation and feedback still go through schema validation, rubric hashing,
    quote checks and provisional-only conversion in app.teaching.application.
    """

    def __init__(self, *, draft=None, proposal=None, feedback_error=None):
        self.draft = draft
        self.proposal = proposal
        self.feedback_error = feedback_error
        self.generated = 0
        self.graded = 0

    async def generate(self, snapshot, material, *, budget):
        from app.teaching.application import CourseApplicationDraft, validate_application_draft

        self.generated += 1
        refs = [item["course_criterion_ref"] for item in snapshot["criteria"]]
        raw = self.draft or {
            "schema_version": "xunke-course-application.v1", "source_policy": snapshot["source_policy"],
            "applications": [application_question(
                "a_return_value", refs[:1],
                prompt="用自己的例子说明一个函数的参数与返回值，并解释调用处如何使用返回值。")],
        }
        draft = CourseApplicationDraft.model_validate(raw)
        validate_application_draft(draft, snapshot, material)
        budget.reserve("llm", input_tokens=400)
        budget.record_output(600)
        return dict(draft=draft.model_dump(mode="json"),
                    evidence={ref: item.model_dump(mode="json") for ref, item in material.evidence.items()},
                    generation_attempts=1)

    async def feedback(self, question, answer, help_usage, material, *, budget):
        from app.teaching.application import ApplicationFeedbackProposal, application_feedback

        self.graded += 1
        if self.feedback_error is not None:
            raise self.feedback_error
        budget.reserve("llm", input_tokens=300)
        budget.record_output(300)
        raw = self.proposal or feedback_proposal(quotes=[answer[:8]])
        return application_feedback(ApplicationFeedbackProposal.model_validate(raw),
                                    question, answer, help_usage)


def owner_worker(store, embedding, generator, **providers):
    from app.rag.engine import RagEngine
    from app.services.source_service import reauthorize_scope
    from app.workers.rag_owner import OwnerWorker

    engine = RagEngine(store, embedding, generator, reauthorize_scope)
    return OwnerWorker(engine, **providers)


@pytest.fixture
def course_worker(platform_settings):
    """Leased OwnerWorker factory over one owner index store per test.

    The store keeps an exclusive owner lock, so every worker in a test shares it
    while each call may install different scripted providers.
    """
    from app.rag.artifact_store import OwnerIndexStore
    from tests.rag.helpers import FixtureEmbedding

    platform_settings.course_enabled = True
    platform_settings.dashscope_embedding_model = "fixture-vector-v1"
    platform_settings.embedding_dimensions = 3
    holder = {}

    def build(quiz=None, *, application=None):
        if "store" not in holder:
            store = OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner")
            store.__enter__()
            holder["store"] = store
        generator = quiz or ScriptedQuizGenerator()
        runner = owner_worker(holder["store"], FixtureEmbedding(), generator,
                              course_application_generator=application)
        return runner, application if application is not None else generator

    yield build
    if "store" in holder:
        holder["store"].__exit__(None, None, None)
