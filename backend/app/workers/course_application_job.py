"""Leased application generation and append-only provisional feedback."""

from app.core.config import get_settings
from app.core.db import execute, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import dump, load, now, uid
from app.learning.contracts import AssessmentDraft
from app.rag.budget import BudgetLedger
from app.rag.contracts import BudgetLimits, DocumentEvidence, stable_hash
from app.services import course_application_service as applications
from app.services import job_service
from app.teaching.application import CourseApplicationDraft, validate_application_draft
from app.teaching.context import TeachingMaterial


def application_material(snapshot, criterion_ids, scope, engine):
    """Use already-published teaching evidence; never retrieve a broader scope."""
    criteria = [item for item in snapshot["criteria"] if item["course_criterion_id"] in criterion_ids]
    lesson_ids = {identity for item in criteria for identity in item["lesson_ids"]}
    material, lessons = TeachingMaterial(), []
    evidence_refs = {}
    for lesson in snapshot["lesson_context"]:
        if lesson["lesson_id"] not in lesson_ids:
            continue
        ref_map = {}
        for old_ref, raw in snapshot.get("lesson_evidence", {}).get(lesson["lesson_id"], {}).items():
            if snapshot["source_policy"] == "topic":
                raise conflict("course_application_topic_evidence", "主题课不能包含资料引用")
            evidence = DocumentEvidence.model_validate(raw)
            engine.verify_evidence(evidence, scope)
            ref = evidence_refs.setdefault(evidence.evidence_id, f"s{len(evidence_refs) + 1}")
            material.evidence[ref] = evidence
            ref_map[old_ref] = ref
        blocks = []
        for block in lesson["blocks"]:
            refs = block.get("source_refs", [])
            if not set(refs) <= set(ref_map):
                raise conflict("course_application_evidence_missing", "已教内容的引用依据不完整")
            blocks.append(dict(block, source_refs=[ref_map[ref] for ref in refs]))
        lessons.append(dict(lesson, blocks=blocks))
    if snapshot["source_policy"] == "strict_docs" and not material.evidence:
        raise conflict("course_application_evidence_missing", "已教内容缺少可用于应用任务的资料依据")
    selected = dict(snapshot, criteria=criteria, lesson_context=lessons)
    return selected, material


def feedback_material(application, scope, engine):
    material = TeachingMaterial()
    question = applications.question_from_row(application)
    for ref, raw in load(application["evidence_json"], {}).items():
        if question.source_policy == "topic":
            raise conflict("course_application_topic_evidence", "主题任务不能包含资料引用")
        evidence = DocumentEvidence.model_validate(raw)
        engine.verify_evidence(evidence, scope)
        material.evidence[ref] = evidence
    if (not set(question.source_refs) <= set(material.evidence)
            or (question.source_policy == "strict_docs" and not material.evidence)):
        raise conflict("course_application_evidence_missing", "应用任务的引用依据不完整")
    return material


async def _preflight(job):
    async with transaction() as conn:
        current = await job_service.locked_job(job, conn)
        return await applications.authorize_application_job(current["user_id"], current, conn=conn)


async def _append_grade(conn, current, context, grade, assessment_id):
    attempt = context["attempt"]
    question = context["question"]
    existing = await fetch_one("SELECT assessment_id FROM learning_course_application_assessments "
                               "WHERE origin_task_id=%s AND owner_id=%s", (current["task_id"], current["user_id"]), conn=conn)
    if existing:
        return existing["assessment_id"]
    await execute(
        "INSERT INTO learning_course_application_assessments(assessment_id,attempt_id,course_assessment_id,course_id,owner_id,"
        "origin_task_id,question_version,rubric_hash,status,confirmation,source,score,feedback_json,independent_eligible,"
        "supersedes_assessment_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (assessment_id, attempt["attempt_id"], attempt["course_assessment_id"], attempt["course_id"], current["user_id"],
         current["task_id"], attempt["question_version"], stable_hash(question.rubric.model_dump(mode="json")),
         grade.status, grade.confirmation, grade.source, grade.score, dump(grade), grade.independent_eligible,
         attempt["latest_assessment_id"]), conn=conn,
    )
    await execute("UPDATE learning_course_application_attempts SET latest_assessment_id=%s,active_task_id=NULL,"
                  "revision=revision+1 WHERE attempt_id=%s AND owner_id=%s AND feedback_task_id=%s",
                  (assessment_id, attempt["attempt_id"], current["user_id"], current["task_id"]), conn=conn)
    return assessment_id


async def run_course_application(job, actor, engine, *, generator, usage_loader):
    if not get_settings().course_enabled:
        raise AppError(409, "course_disabled", "课程生成功能暂未启用")
    if generator is None:
        raise AppError(503, "course_provider_unavailable", "课程模型暂未配置")
    if actor.owner_id != job["user_id"]:
        raise not_found()
    context = await _preflight(job)
    generation = job["kind"] == "course_application_generate"
    budget = BudgetLedger(BudgetLimits(
        max_llm_calls=3 if generation else 2, max_embedding_calls=0,
        max_reranker_calls=0, max_search_calls=0, max_fetch_calls=0,
        max_input_tokens=32000, max_output_tokens=8192 if generation else 3200,
        deadline_seconds=max(.001, min(1800, (job["deadline_at"] - now()).total_seconds())),
    ))
    await job_service.heartbeat(job, "preparing_application_sources")
    if generation:
        selected, material = application_material(context["snapshot"], job["request"]["course_criterion_ids"],
                                                   context["scope"], engine)
        await job_service.heartbeat(job, "generating_application")
        generated = await generator.generate(selected, material, budget=budget)
        draft = CourseApplicationDraft.model_validate(generated["draft"])
        validate_application_draft(draft, selected, material)
        application_ids = [uid("application") for _ in draft.applications]
        result = dict(course_id=job["request"]["course_id"], course_assessment_id=job["request"]["course_assessment_id"],
                      application_task_ids=application_ids,
                      usage=await usage_loader(job, budget.snapshot().model_dump(mode="json")))

        async def publish(current, public, conn):
            saved = await applications.authorize_application_job(actor.owner_id, current, conn=conn)
            refreshed, fresh_material = application_material(saved["snapshot"], current["request"]["course_criterion_ids"],
                                                              saved["scope"], engine)
            if refreshed != selected or fresh_material.evidence != material.evidence:
                raise conflict("revision_conflict", "应用任务的教学内容已变化")
            validate_application_draft(draft, refreshed, fresh_material)
            goal_ids = {item["course_criterion_ref"]: item["course_criterion_id"] for item in selected["criteria"]}
            for position, (identity, question) in enumerate(zip(application_ids, draft.applications)):
                private = question.model_dump(mode="json")
                await execute(
                    "INSERT INTO learning_course_application_tasks(application_task_id,course_assessment_id,course_id,owner_id,"
                    "generation_task_id,application_ref,position,question_version,draft_json,evidence_json,course_criterion_ids_json) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (identity, saved["assessment"]["course_assessment_id"], saved["assessment"]["course_id"], actor.owner_id,
                     current["task_id"], question.application_ref, position, stable_hash(private), dump(private),
                     dump({ref: fresh_material.evidence[ref].model_dump(mode="json") for ref in question.source_refs}),
                     dump([goal_ids[ref] for ref in question.course_criterion_refs])), conn=conn,
                )
            await execute("UPDATE learning_course_assessments SET revision=revision+1,updated_at=%s "
                          "WHERE course_assessment_id=%s AND owner_id=%s",
                          (now(), saved["assessment"]["course_assessment_id"], actor.owner_id), conn=conn)
    else:
        material = feedback_material(context["application"], context["scope"], engine)
        await job_service.heartbeat(job, "grading_application")
        proposed = await generator.feedback(context["question"], context["attempt"]["answer_text"],
                                            context["attempt"]["help_usage"], material, budget=budget)
        grade = AssessmentDraft.model_validate(proposed.model_dump(mode="json") if hasattr(proposed, "model_dump") else proposed)
        # A model response cannot grant itself formal confirmation, even through
        # an injected adapter. Human review is a separate, permissioned command.
        grade = grade.model_copy(update={"source": "model", "confirmation": "provisional", "independent_eligible": False})
        if grade.rubric_hash != stable_hash(context["question"].rubric.model_dump(mode="json")):
            raise conflict("course_application_feedback_invalid", "反馈评分条目与题目不匹配")
        assessment_id = uid("application_grade")
        result = dict(course_id=job["request"]["course_id"], course_assessment_id=job["request"]["course_assessment_id"],
                      application_task_id=context["application"]["application_task_id"], attempt_id=context["attempt"]["attempt_id"],
                      assessment_id=assessment_id, usage=await usage_loader(job, budget.snapshot().model_dump(mode="json")))

        async def publish(current, public, conn):
            saved = await applications.authorize_application_job(actor.owner_id, current, conn=conn)
            fresh_material = feedback_material(saved["application"], saved["scope"], engine)
            if (saved["question"] != context["question"] or saved["attempt"]["answer_text"] != context["attempt"]["answer_text"]
                    or fresh_material.evidence != material.evidence):
                raise conflict("revision_conflict", "应用任务或回答的冻结内容已变化")
            await _append_grade(conn, current, saved, grade, assessment_id)
    await job_service.heartbeat(job, "saving_application")
    await job_service.complete_job(job, result, publisher=publish)


async def reconcile_course_application(job, conn):
    if job.get("kind") not in applications.KINDS or job["status"] not in {"failed", "cancelled"}:
        return
    request = job.get("request") or {}
    if not request.get("course_id") or not request.get("course_assessment_id"):
        return
    # Terminal cleanup also works after revocation. It never reconstructs text
    # or grants access to removed source material.
    if job["kind"] == "course_application_generate":
        return
    raw = await fetch_one("SELECT * FROM learning_course_application_attempts WHERE attempt_id=%s "
                          "AND course_id=%s AND course_assessment_id=%s AND owner_id=%s FOR UPDATE",
                          (request.get("attempt_id"), request["course_id"], request["course_assessment_id"], job["user_id"]), conn=conn)
    if raw is None or raw["feedback_task_id"] != job["task_id"]:
        return
    if raw["revoked_at"] is not None:
        await execute("UPDATE learning_course_application_attempts SET active_task_id=NULL WHERE attempt_id=%s "
                      "AND owner_id=%s AND active_task_id=%s", (raw["attempt_id"], job["user_id"], job["task_id"]), conn=conn)
        return
    existing = await fetch_one("SELECT assessment_id FROM learning_course_application_assessments "
                               "WHERE origin_task_id=%s AND owner_id=%s", (job["task_id"], job["user_id"]), conn=conn)
    if existing:
        return
    application = await applications.owned_application(job["user_id"], raw["course_id"], raw["course_assessment_id"],
                                                       raw["application_task_id"], conn=conn)
    question = applications.question_from_row(application)
    grade = AssessmentDraft(status=job["status"], confirmation="provisional", source="model",
                            grader_version="course-application-feedback-v1", rubric_version=question.rubric.version,
                            rubric_hash=stable_hash(question.rubric.model_dump(mode="json")),
                            feedback="回答已保存，反馈未完成；可稍后重试。")
    await _append_grade(conn, job, dict(attempt=raw, question=question), grade, uid("application_grade"))
