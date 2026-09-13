"""Frozen course checks reuse quiz publication, answers and settlement facts."""

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, load, now, uid
from app.models.course_assessment import CourseAssessmentTask, CourseAssessmentView
from app.models.task_event import business_settled_from
from app.rag.contracts import QuizSpec, ResolvedScope, stable_hash
from app.services import course_outcome_service, course_read, job_service, quiz_service


def _key(key):
    if not key or len(key) > 128:
        raise AppError(422, "idempotency_required", "需要有效 Idempotency-Key")


async def owned_assessment(owner, course_id, assessment_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM learning_course_assessments WHERE course_assessment_id=%s "
        "AND course_id=%s AND owner_id=%s" + (" FOR UPDATE" if lock else ""),
        (assessment_id, course_id, owner), conn=conn,
    )
    if row is None:
        raise not_found()
    if row["revoked_at"] is not None or row["snapshot_json"] is None:
        raise AppError(404, "source_revoked", "结业检查关联资料已失效")
    return row


async def authorized_assessment(owner, course_id, assessment_id, *, conn=None,
                                lock=False, require_active=False):
    course = await course_read.owned_course(owner, course_id, conn=conn, lock=lock)
    row = await owned_assessment(owner, course_id, assessment_id, conn=conn, lock=lock)
    snapshot = load(row["snapshot_json"])
    if require_active:
        current = {item["course_criterion_id"]: item for item in await course_outcome_service.criterion_rows(
            owner, course_id, course["criteria_revision"], conn=conn,
        )}
        selected = set(snapshot["selected_criterion_ids"])
        for criterion in snapshot["criteria"]:
            if criterion["course_criterion_id"] not in selected:
                continue
            live = current.get(criterion["course_criterion_id"])
            if live is None or live["definition_hash"] != criterion["definition_hash"]:
                raise conflict("revision_conflict", "课程目标已更新，请创建新一组检查")
            for lesson_id, version in sorted(criterion["lesson_versions"].items()):
                lesson = await course_read.owned_lesson(owner, course_id, lesson_id, conn=conn, lock=lock)
                if lesson["content_version"] != version or lesson["status"] != "ready":
                    raise conflict("revision_conflict", "关联课文已更新，请创建新一组检查")
    scope = await course_read.authorize_course(course, conn=conn)
    frozen_scope = ResolvedScope.model_validate(load(row["scope_json"]))
    if (scope != frozen_scope or row["scope_fingerprint"] != scope.fingerprint
            or row["source_policy"] != course["source_policy"]):
        raise AppError(404, "source_revoked", "结业检查来源范围已发生变化")
    return course, row, scope


async def task_summary(owner, task_id, *, conn=None):
    if task_id is None:
        return None
    row = await fetch_one(
        "SELECT task_id,status,stage,error_code FROM quiz_tasks WHERE task_id=%s "
        "AND user_id=%s AND mode='production'", (task_id, owner), conn=conn,
    )
    if row is None:
        raise not_found()
    errors = {
        "revision_conflict": "课程内容已更新，请创建新一组检查",
        "source_revoked": "关联资料已失效",
        "deadline_exceeded": "生成超时，请稍后重试",
        "provider_unavailable": "模型服务暂不可用，请稍后重试",
        "course_application_input_too_large": "本组课文过长，请减少所选目标",
    }
    return CourseAssessmentTask(
        **row, error_message=errors.get(row["error_code"], "处理未完成，请稍后重试")
        if row["error_code"] else None,
        business_settled=business_settled_from(row["status"], row["stage"]),
    ).model_dump(mode="json")


async def _snapshot(owner, course_id, body, *, conn=None, lock=False):
    course = await course_read.owned_course(owner, course_id, conn=conn, lock=lock)
    if course["status"] not in {"ready", "partial"}:
        raise conflict("course_not_ready", "请先完成课程纲要和相关课文")
    if (course["revision"] != body.expected_course_revision
            or course["criteria_revision"] != body.expected_criteria_revision):
        raise conflict("revision_conflict", "课程或目标已更新，请刷新后重试")
    definitions = await course_outcome_service.criterion_rows(owner, course_id, course["criteria_revision"], conn=conn)
    lessons = await fetch_all(
        "SELECT * FROM learning_course_lessons WHERE course_id=%s AND owner_id=%s "
        "ORDER BY lesson_id" + (" FOR UPDATE" if lock else ""), (course_id, owner), conn=conn,
    )
    scope = await course_read.authorize_course(course, conn=conn)
    lesson_map = {item["lesson_id"]: item for item in lessons}
    criteria = []
    for definition in definitions:
        item = course_outcome_service.criterion_view(definition).model_dump(mode="json")
        related = [lesson_map[identity] for identity in item["lesson_ids"] if identity in lesson_map]
        item.update(
            definition_hash=definition["definition_hash"],
            lesson_versions={identity: lesson_map[identity]["content_version"] for identity in item["lesson_ids"]},
            available=bool(related) and all(lesson["status"] == "ready" and lesson["content_json"] for lesson in related),
        )
        criteria.append(item)
    known = {item["course_criterion_id"] for item in criteria}
    if not set(body.course_criterion_ids) <= known:
        raise AppError(422, "course_criterion_invalid", "所选目标不属于当前课程版本")
    requested = set(body.course_criterion_ids) if body.course_criterion_ids else known
    selected = [item["course_criterion_id"] for item in criteria
                if item["course_criterion_id"] in requested and item["available"]]
    if not selected:
        raise conflict("course_assessment_no_taught_goals", "请先完成至少一个目标的关联课文；资料缺口目标仍保持待验证")
    # A short group never claims to cover the whole curriculum. Prioritize
    # recognition goals; other types may be checked but cannot be verified by it.
    candidates = [item for item in criteria if item["course_criterion_id"] in selected]
    candidates.sort(key=lambda item: item["evidence_type"] != "recognition")
    quiz_ids = [item["course_criterion_id"] for item in candidates[:3]]
    used_lessons = {identity for item in criteria if item["course_criterion_id"] in selected
                    for identity in item["lesson_ids"]}
    context, evidence = [], {}
    for lesson in lessons:
        if lesson["lesson_id"] not in used_lessons:
            continue
        payload = (load(lesson["content_json"], {}).get("payload") or {})
        unit = load(lesson["unit_json"], {})
        context.append(dict(
            lesson_id=lesson["lesson_id"], content_version=lesson["content_version"],
            title=unit.get("title", ""), objective=payload.get("objective") or unit.get("objective", ""),
            blocks=[{key: block[key] for key in ("type", "text", "source_refs") if key in block}
                    for block in payload.get("blocks", [])],
        ))
        evidence[lesson["lesson_id"]] = load(lesson["evidence_json"], {})
    return course, scope, dict(source_policy=course["source_policy"], criteria=criteria,
                               selected_criterion_ids=selected, quiz_criterion_ids=quiz_ids,
                               lesson_context=context, lesson_evidence=evidence)


def _quiz_spec(course, snapshot):
    goals = [item for item in snapshot["criteria"] if item["course_criterion_id"] in snapshot["quiz_criterion_ids"]]
    related = {identity for item in goals for identity in item["lesson_ids"]}
    sections = [lesson for lesson in snapshot["lesson_context"] if lesson["lesson_id"] in related]
    context = "\n".join(
        f"{lesson['title']}：{lesson['objective']}\n" + "\n".join(block.get("text", "") for block in lesson["blocks"])
        for lesson in sections
    )
    prefix = "课程结业客观检查，只检查以下已教内容及提供的明确目标，不引入其他课程。\n"
    return QuizSpec(
        user_input=prefix + context[:2000 - len(prefix)], question_count=min(6, max(3, 2 * len(goals))),
        difficulty="mixed", source_policy=course["source_policy"],
        scope=load(course["requested_scope_json"]) if course["source_policy"] == "strict_docs" else None,
        objective_titles=[item["description"] for item in goals],
        course_criteria=[{key: item[key] for key in (
            "course_criterion_ref", "description", "evidence_type", "expectation"
        )} for item in goals],
    )


async def create_course_assessment(actor, course_id, body, key):
    from app.services.course_service import require_enabled

    _key(key)
    owner = actor.owner_id
    request_hash = digest(dump(dict(operation="course.assessment.create", course_id=course_id,
                                   **body.model_dump(mode="json"))))
    old = await fetch_one("SELECT * FROM learning_course_assessments WHERE owner_id=%s AND idempotency_key=%s",
                          (owner, key))
    if old:
        if old["request_hash"] != request_hash:
            raise conflict("idempotency_conflict", "相同操作标识已用于不同请求")
        return await get_course_assessment(owner, course_id, old["course_assessment_id"])
    require_enabled()
    await course_outcome_service.get_course_criteria(owner, course_id)
    course, scope, snapshot = await _snapshot(owner, course_id, body)
    spec, assessment_id = _quiz_spec(course, snapshot), uid("course_assessment")
    saved_id = assessment_id

    async def bind(job, conn):
        nonlocal saved_id
        existing = await fetch_one("SELECT * FROM learning_course_assessments WHERE task_id=%s AND owner_id=%s",
                                   (job["task_id"], owner), conn=conn)
        if existing:
            if existing["request_hash"] != request_hash or existing["course_id"] != course_id:
                raise conflict("idempotency_conflict", "相同操作标识已用于不同请求")
            await authorized_assessment(owner, course_id, existing["course_assessment_id"], conn=conn, lock=True)
            saved_id = existing["course_assessment_id"]
            return
        saved_course, saved_scope, saved_snapshot = await _snapshot(owner, course_id, body, conn=conn, lock=True)
        if saved_scope != scope or saved_snapshot != snapshot:
            raise conflict("revision_conflict", "课程内容已更新，请刷新后重试")
        await execute(
            "INSERT INTO learning_course_assessments(course_assessment_id,course_id,owner_id,criteria_revision,"
            "course_revision,source_policy,scope_json,scope_fingerprint,snapshot_json,task_id,idempotency_key,request_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (assessment_id, course_id, owner, saved_course["criteria_revision"], saved_course["revision"],
             course["source_policy"], dump(scope), scope.fingerprint, dump(snapshot), job["task_id"], key, request_hash), conn=conn,
        )
    async with transaction() as conn:
        await quiz_service.enqueue_resolved_quiz(actor, spec, scope, key, conn=conn,
                                                 request_hash=request_hash, before_authorize=bind)
    return await get_course_assessment(owner, course_id, saved_id)


async def authorize_assessment_quiz_job(owner, job, *, conn=None, require_active=True):
    link = await fetch_one("SELECT course_id,course_assessment_id FROM learning_course_assessments "
                           "WHERE task_id=%s AND owner_id=%s", (job["task_id"], owner), conn=conn)
    if link is None:
        return None
    if job.get("kind") != "quiz" or job.get("mode") != "production" or job.get("user_id") != owner:
        raise not_found()
    course, row, scope = await authorized_assessment(
        owner, link["course_id"], link["course_assessment_id"], conn=conn, lock=conn is not None,
        require_active=require_active,
    )
    spec, learning_context = quiz_service.parse_quiz_request(job["request"])
    if (learning_context is not None or scope != ResolvedScope.model_validate(job["scope"])
            or spec != _quiz_spec(course, load(row["snapshot_json"]))):
        raise not_found()
    return row


def objective_question_version(question):
    # Image decoration may finish later and is not part of a grading identity.
    return stable_hash({key: value for key, value in question.items()
                        if key not in {"image_url", "image_status", "image_prompt"}})


async def publish_assessment_quiz(conn, owner, job, artifact):
    row = await authorize_assessment_quiz_job(owner, job, conn=conn)
    if row is None:
        return
    raw = artifact.model_dump(mode="json") if hasattr(artifact, "model_dump") else artifact
    snapshot = load(row["snapshot_json"])
    goals = {item["course_criterion_ref"]: item for item in snapshot["criteria"]
             if item["course_criterion_id"] in snapshot["quiz_criterion_ids"]}
    questions = raw["questions"]
    spec, _ = quiz_service.parse_quiz_request(job["request"])
    if len(questions) != spec.question_count:
        raise conflict("course_assessment_invalid", "客观题数量与冻结范围不符")
    for question in questions:
        refs = question.get("course_criterion_refs", [])
        if not refs or len(refs) != len(set(refs)) or not set(refs) <= set(goals):
            raise conflict("course_assessment_invalid", "客观题缺少有效课程目标对应")
        for ref in refs:
            await execute(
                "INSERT INTO learning_course_assessment_questions(course_assessment_id,course_id,owner_id,quiz_id,"
                "question_id,question_version,course_criterion_id,criteria_revision) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (row["course_assessment_id"], row["course_id"], owner, job["quiz_id"], question["id"],
                 objective_question_version(question), goals[ref]["course_criterion_id"], row["criteria_revision"]), conn=conn,
            )
    await execute(
        "UPDATE learning_course_assessments SET quiz_id=%s,status='ready',revision=revision+1,updated_at=%s "
        "WHERE course_assessment_id=%s AND owner_id=%s AND quiz_id IS NULL",
        (job["quiz_id"], now(), row["course_assessment_id"], owner), conn=conn,
    )


async def authorize_assessment_quiz(owner, quiz_id, *, conn=None, for_write=False):
    link = await fetch_one("SELECT course_id,course_assessment_id FROM learning_course_assessments "
                           "WHERE quiz_id=%s AND owner_id=%s", (quiz_id, owner), conn=conn)
    if link is None:
        return None
    _, row, _ = await authorized_assessment(owner, link["course_id"], link["course_assessment_id"],
                                           conn=conn, lock=for_write, require_active=for_write)
    return row


async def record_quiz_settlement(conn, owner, quiz_id):
    """Only settle mappings from an already committed-in-this-tx quiz receipt."""
    row = await authorize_assessment_quiz(owner, quiz_id, conn=conn)
    if row is None:
        return
    quiz = await fetch_one("SELECT * FROM quiz_sessions WHERE quiz_id=%s AND user_id=%s", (quiz_id, owner), conn=conn)
    records = await fetch_one("SELECT records_json FROM answer_records WHERE quiz_id=%s AND user_id=%s",
                              (quiz_id, owner), conn=conn)
    if quiz["status"] != "settled" or quiz["settled_at"] is None or records is None:
        return
    questions = {item["id"]: item for item in load(quiz["questions_json"], [])}
    answers = {item["question_id"]: item for item in load(records["records_json"], [])}
    mappings = await fetch_all("SELECT question_id,question_version FROM learning_course_assessment_questions "
                               "WHERE quiz_id=%s AND owner_id=%s", (quiz_id, owner), conn=conn)
    for mapping in mappings:
        identity = mapping["question_id"]
        question, answer = questions.get(identity), answers.get(identity)
        if (question is None or answer is None or type(answer.get("is_correct")) is not bool
                or objective_question_version(question) != mapping["question_version"]):
            raise conflict("course_assessment_evidence_changed", "检查题目或结算证据已变化")
        await execute(
            "UPDATE learning_course_assessment_questions SET settlement_json=%s,settled_at=%s "
            "WHERE quiz_id=%s AND owner_id=%s AND question_id=%s AND settlement_json IS NULL",
            (dump(dict(is_correct=answer["is_correct"], confirmation="confirmed", source="deterministic")),
             quiz["settled_at"], quiz_id, owner, identity), conn=conn,
        )
    await execute(
        "UPDATE learning_course_assessments SET status='in_progress',revision=revision+1,updated_at=%s "
        "WHERE course_assessment_id=%s AND owner_id=%s AND status='ready'",
        (now(), row["course_assessment_id"], owner), conn=conn,
    )


async def _view(row, *, conn=None):
    from app.services.course_application_service import application_views

    owner, snapshot = row["owner_id"], load(row["snapshot_json"])
    task = await task_summary(owner, row["task_id"], conn=conn)
    quiz = await fetch_one("SELECT status,settled_at FROM quiz_sessions WHERE quiz_id=%s AND user_id=%s",
                           (row["quiz_id"], owner), conn=conn) if row["quiz_id"] else None
    applications = await application_views(owner, row["course_assessment_id"], conn=conn)
    covered = {item["course_criterion_id"] for item in await fetch_all(
        "SELECT DISTINCT course_criterion_id FROM learning_course_assessment_questions "
        "WHERE course_assessment_id=%s AND owner_id=%s", (row["course_assessment_id"], owner), conn=conn,
    )}
    # An unanswered application is visible, but still uncovered learning work.
    covered.update(identity for app in applications if app["latest_attempt_id"] for identity in app["course_criterion_ids"])
    status = row["status"]
    if status == "generating" and task["status"] in {"failed", "cancelled"}:
        status = task["status"]
    return CourseAssessmentView(
        course_assessment_id=row["course_assessment_id"], course_id=row["course_id"],
        criteria_revision=row["criteria_revision"], revision=row["revision"], status=status,
        task_id=row["task_id"], task=task, quiz_id=row["quiz_id"] if quiz else None,
        quiz_status=quiz["status"] if quiz else None,
        quiz_settled=bool(quiz and quiz["status"] == "settled" and quiz["settled_at"]),
        application_generation_task_id=row["application_generation_task_id"],
        application_generation_task=await task_summary(owner, row["application_generation_task_id"], conn=conn),
        application_task_ids=[item["application_task_id"] for item in applications], applications=applications,
        covered_course_criterion_ids=sorted(covered),
        uncovered_course_criterion_ids=[item["course_criterion_id"] for item in snapshot["criteria"]
                                        if item["course_criterion_id"] not in covered],
    ).model_dump(mode="json")


async def get_course_assessment(owner, course_id, course_assessment_id, *, conn=None):
    course, row, _ = await authorized_assessment(owner, course_id, course_assessment_id, conn=conn)
    result = await _view(row, conn=conn)
    await course_read.authorize_course(course, conn=conn)
    return result


async def list_course_assessments(owner, course_id):
    course = await course_read.owned_course(owner, course_id)
    await course_read.authorize_course(course)
    rows = await fetch_all("SELECT course_assessment_id FROM learning_course_assessments "
                           "WHERE owner_id=%s AND course_id=%s AND revoked_at IS NULL "
                           "ORDER BY created_at DESC,course_assessment_id DESC LIMIT 50", (owner, course_id))
    return [await get_course_assessment(owner, course_id, row["course_assessment_id"]) for row in rows]


async def complete_course_assessment(owner, course_id, course_assessment_id, body, key):
    _key(key)
    request_hash = digest(dump(dict(course_id=course_id, course_assessment_id=course_assessment_id,
                                   **body.model_dump(mode="json"))))
    async with transaction() as conn:
        _, row, _ = await authorized_assessment(owner, course_id, course_assessment_id, conn=conn, lock=True)
        if row["completed_at"]:
            if row["completion_key"] != key or row["completion_hash"] != request_hash:
                raise conflict("course_assessment_completed", "本次检查已封存，请创建下一组检查")
            return await _view(row, conn=conn)
        if row["revision"] != body.expected_revision:
            raise conflict("revision_conflict", "检查进度已更新，请刷新后重试")
        duplicate = await fetch_one("SELECT course_assessment_id FROM learning_course_assessments "
                                    "WHERE owner_id=%s AND completion_key=%s", (owner, key), conn=conn)
        if duplicate:
            raise conflict("idempotency_conflict", "相同操作标识已用于其他检查")
        quiz = await fetch_one("SELECT status,settled_at FROM quiz_sessions WHERE quiz_id=%s AND user_id=%s",
                               (row["quiz_id"], owner), conn=conn)
        if not quiz or quiz["status"] != "settled" or quiz["settled_at"] is None:
            raise conflict("course_assessment_incomplete", "请先完成并结算本组客观题")
        await record_quiz_settlement(conn, owner, row["quiz_id"])
        attempts = await fetch_all("SELECT attempt_id FROM learning_course_application_attempts "
                                    "WHERE course_assessment_id=%s AND owner_id=%s AND revoked_at IS NULL "
                                    "ORDER BY saved_at,attempt_id", (course_assessment_id, owner), conn=conn)
        completion = dict(help_usage=body.help_usage,
                          help_usage_source="unknown" if body.help_usage == "unknown" else "learner_declaration",
                          # This objective flow exposes no pre-answer system hint.
                          system_hints_used=False,
                          attempt_ids=[item["attempt_id"] for item in attempts])
        await execute(
            "UPDATE learning_course_assessments SET status='completed',revision=revision+1,completion_key=%s,"
            "completion_hash=%s,completion_json=%s,completed_at=%s,updated_at=%s "
            "WHERE course_assessment_id=%s AND owner_id=%s",
            (key, request_hash, dump(completion), now(), now(), course_assessment_id, owner), conn=conn,
        )
        return await get_course_assessment(owner, course_id, course_assessment_id, conn=conn)


async def purge_course_assessments(conn, owner, course_id):
    """Keep identities as tombstones; remove every private course derivative."""
    stamp = now()
    await execute("UPDATE learning_course_application_assessments SET feedback_json=NULL "
                  "WHERE owner_id=%s AND course_id=%s", (owner, course_id), conn=conn)
    await execute("UPDATE learning_course_application_attempts SET answer_text=NULL,active_task_id=NULL,"
                  "revoked_at=COALESCE(revoked_at,%s) WHERE owner_id=%s AND course_id=%s", (stamp, owner, course_id), conn=conn)
    await execute("UPDATE learning_course_application_tasks SET draft_json=NULL,evidence_json=NULL,"
                  "revoked_at=COALESCE(revoked_at,%s) WHERE owner_id=%s AND course_id=%s", (stamp, owner, course_id), conn=conn)
    await execute("UPDATE learning_course_assessment_questions SET settlement_json=NULL "
                  "WHERE owner_id=%s AND course_id=%s", (owner, course_id), conn=conn)
    await execute("UPDATE learning_course_assessments SET snapshot_json=NULL,scope_json=NULL,completion_json=NULL,"
                  "status='source_revoked',revoked_at=COALESCE(revoked_at,%s),updated_at=%s "
                  "WHERE owner_id=%s AND course_id=%s", (stamp, stamp, owner, course_id), conn=conn)
    await execute("UPDATE learning_course_criteria SET description=NULL,expectation=NULL,"
                  "revoked_at=COALESCE(revoked_at,%s) WHERE owner_id=%s AND course_id=%s", (stamp, owner, course_id), conn=conn)


async def delete_course_assessments(conn, owner):
    # Break the latest pointer and the supersedes links before deleting the
    # two mutually referencing tables during an explicit account deletion.
    await execute("UPDATE learning_course_application_attempts SET latest_assessment_id=NULL WHERE owner_id=%s", (owner,), conn=conn)
    await execute("UPDATE learning_course_application_assessments SET supersedes_assessment_id=NULL WHERE owner_id=%s", (owner,), conn=conn)
    for table in ("learning_course_application_assessments", "learning_course_application_attempts",
                  "learning_course_application_tasks", "learning_course_assessment_questions",
                  "learning_course_assessments", "learning_course_criteria"):
        await execute(f"DELETE FROM {table} WHERE owner_id=%s", (owner,), conn=conn)
