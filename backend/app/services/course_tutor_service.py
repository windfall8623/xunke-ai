"""Owner-scoped, versioned tutor turns with durable tasks and private evidence."""

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.security import check_content
from app.core.values import digest, dump, iso, load, now, uid
from app.models.course_tutor import CourseTutorTurnView
from app.rag.contracts import DocumentEvidence
from app.rag.scope import evidence_in_scope
from app.services import course_read, job_service, source_service
from app.services.course_service import require_enabled


def check_lesson_version(lesson, content_version):
    if lesson["content_version"] != content_version:
        raise conflict("revision_conflict", "课时内容版本已变化，请刷新后重试")
    if lesson["status"] != "ready" or not lesson["content_json"]:
        raise conflict("course_lesson_not_ready", "请先生成本课内容")


async def authorized_lesson(owner, course_id, lesson_id, content_version=None, *, conn=None, lock=False):
    course = await course_read.owned_course(owner, course_id, conn=conn, lock=lock)
    lesson = await course_read.owned_lesson(owner, course_id, lesson_id, conn=conn, lock=lock)
    scope = await course_read.authorize_course(course, conn=conn)
    check_lesson_version(lesson, lesson["content_version"] if content_version is None else content_version)
    return course, lesson, scope


async def owned_turn(owner, course_id, lesson_id, turn_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM learning_course_tutor_turns WHERE turn_id=%s AND owner_id=%s "
        "AND course_id=%s AND lesson_id=%s" + (" FOR UPDATE" if lock else ""),
        (turn_id, owner, course_id, lesson_id), conn=conn,
    )
    if not row:
        raise not_found()
    if row["revoked_at"] is not None or row["question"] is None:
        raise AppError(404, "source_revoked", "助教回答关联资料已失效")
    return row


async def _turn_view(row, *, conn=None):
    task = await course_read.task_view(
        row["owner_id"], row["last_task_id"], row["course_id"], row["lesson_id"], conn=conn
    )
    # Both are committed by the same fenced publication transaction.
    response = load(row["response_json"], {}) if task["status"] == "completed" else {}
    return CourseTutorTurnView(
        turn_id=row["turn_id"], course_id=row["course_id"], lesson_id=row["lesson_id"],
        content_version=row["content_version"], mode=row["mode"], block_index=row["block_index"],
        question=row["question"], check_attempt_id=row["check_attempt_id"], task=task,
        answer=response.get("answer"), sources=response.get("sources", []),
        warnings=response.get("warnings", []), created_at=iso(row["created_at"]),
    ).model_dump(mode="json")


async def get_turn(owner, course_id, lesson_id, turn_id, *, conn=None):
    course, lesson, _ = await authorized_lesson(owner, course_id, lesson_id, conn=conn)
    row = await owned_turn(owner, course_id, lesson_id, turn_id, conn=conn)
    check_lesson_version(lesson, row["content_version"])
    result = await _turn_view(row, conn=conn)
    await course_read.authorize_course(course, conn=conn)
    return result


async def list_turns(owner, course_id, lesson_id, content_version):
    course, _, _ = await authorized_lesson(owner, course_id, lesson_id, content_version)
    rows = await fetch_all(
        "SELECT * FROM learning_course_tutor_turns WHERE owner_id=%s AND course_id=%s "
        "AND lesson_id=%s AND content_version=%s AND revoked_at IS NULL "
        "ORDER BY created_at,turn_id", (owner, course_id, lesson_id, content_version),
    )
    result = [await _turn_view(row) for row in rows]
    await course_read.authorize_course(course)
    return result


async def latest_turn_for_attempt(owner, course_id, lesson_id, content_version, attempt_id, *, conn=None):
    row = await fetch_one(
        "SELECT * FROM learning_course_tutor_turns WHERE owner_id=%s AND course_id=%s "
        "AND lesson_id=%s AND content_version=%s AND check_attempt_id=%s AND revoked_at IS NULL "
        "ORDER BY created_at DESC,turn_id DESC LIMIT 1",
        (owner, course_id, lesson_id, content_version, attempt_id), conn=conn,
    )
    return await _turn_view(row, conn=conn) if row else None


async def authorize_tutor_task(owner, task_id, request, *, conn=None):
    """Used by the shared course task route, including historical retry tasks."""
    if not isinstance(request, dict) or not all(
        request.get(field) for field in ("course_id", "lesson_id", "turn_id", "expected_content_version")
    ):
        raise not_found()
    _, lesson, scope = await authorized_lesson(
        owner, request["course_id"], request["lesson_id"], request["expected_content_version"], conn=conn
    )
    row = await owned_turn(owner, request["course_id"], request["lesson_id"], request["turn_id"], conn=conn)
    stored = await fetch_one(
        "SELECT request_json FROM quiz_tasks WHERE task_id=%s AND user_id=%s "
        "AND kind='course_tutor' AND operation='course.tutor' AND mode='production'",
        (task_id, owner), conn=conn,
    )
    if (not stored or load(stored["request_json"]) != request
            or row["content_version"] != lesson["content_version"]
            or request.get("scope_fingerprint") != scope.fingerprint):
        raise not_found()
    return row


async def _validate_turn_input(owner, course_id, lesson_id, lesson, body, *, conn=None):
    blocks = (load(lesson["content_json"], {}).get("payload") or {}).get("blocks", [])
    if body.block_index is not None and not 0 <= body.block_index < len(blocks):
        raise AppError(422, "course_block_invalid", "所选段落不属于当前课时")
    context = None
    if body.mode == "check":
        from app.services.course_self_check_service import check_attempt_context

        context = await check_attempt_context(
            owner, course_id, lesson_id, body.check_attempt_id, lesson, conn=conn
        )
    text = body.question + ("\n" + dump(context["answer"]) if context else "")
    if not check_content(text):
        raise AppError(422, "content_filtered", "请调整问题或回答后重试")
    return context


def _request(course_id, lesson_id, turn_id, version, scope):
    # Sensitive input is stored once on the turn, not duplicated in task payloads.
    return dict(
        course_id=course_id, lesson_id=lesson_id, turn_id=turn_id,
        expected_content_version=version, scope_fingerprint=scope.fingerprint,
        pipeline_id=get_settings().rag_pipeline_id,
    )


async def _ensure_no_active_turn(owner, course_id, lesson_id, version, *, conn, excluding=None):
    rows = await fetch_all(
        "SELECT turn_id,active_task_id FROM learning_course_tutor_turns "
        "WHERE owner_id=%s AND course_id=%s AND lesson_id=%s AND content_version=%s "
        "AND active_task_id IS NOT NULL FOR UPDATE",
        (owner, course_id, lesson_id, version), conn=conn,
    )
    for row in rows:
        if row["turn_id"] == excluding:
            continue
        # Terminal jobs never become running again; retry allocates a new task.
        # Do not lock this older task after locking the lesson and turn.
        task = await fetch_one(
            "SELECT status FROM quiz_tasks WHERE task_id=%s AND user_id=%s",
            (row["active_task_id"], owner), conn=conn,
        )
        if task and task["status"] in course_read.TERMINAL:
            await execute(
                "UPDATE learning_course_tutor_turns SET active_task_id=NULL,updated_at=%s "
                "WHERE turn_id=%s AND owner_id=%s AND active_task_id=%s",
                (now(), row["turn_id"], owner, row["active_task_id"]), conn=conn,
            )
        else:
            raise conflict("course_tutor_busy", "本课还有助教回答正在生成，请等待完成或取消后再提问")


async def create_turn(actor, course_id, lesson_id, body, key):
    require_enabled()
    owner = actor.owner_id
    _, lesson, scope = await authorized_lesson(owner, course_id, lesson_id, body.expected_content_version)
    await _validate_turn_input(owner, course_id, lesson_id, lesson, body)
    request_hash = digest(dump(dict(operation="create_turn", course_id=course_id, lesson_id=lesson_id,
                                    **body.model_dump(mode="json"))))
    old = await job_service.existing_job(owner, "course_tutor", key, request_hash)
    if old:
        return await get_turn(owner, course_id, lesson_id, old["request"]["turn_id"])
    turn_id = uid("turn")
    request = _request(course_id, lesson_id, turn_id, body.expected_content_version, scope)
    async with transaction() as conn:
        # Queue reservation always precedes course/lesson locks, as in course jobs.
        job = await job_service.enqueue_job(
            owner, "course_tutor", request, key, scope=scope.model_dump(mode="json"),
            request_hash=request_hash, conn=conn,
        )
        _, lesson, saved_scope = await authorized_lesson(
            owner, course_id, lesson_id, body.expected_content_version, conn=conn, lock=True
        )
        if saved_scope != scope:
            raise conflict("course_scope_changed", "课程来源已发生变化")
        saved_id = job["request"]["turn_id"]
        if saved_id == turn_id:
            await _validate_turn_input(owner, course_id, lesson_id, lesson, body, conn=conn)
            await _ensure_no_active_turn(owner, course_id, lesson_id, body.expected_content_version, conn=conn)
            await execute(
                "INSERT INTO learning_course_tutor_turns(turn_id,course_id,lesson_id,owner_id,content_version,"
                "mode,block_index,question,check_attempt_id,creation_task_id,last_task_id,active_task_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (turn_id, course_id, lesson_id, owner, body.expected_content_version, body.mode,
                 body.block_index, body.question, body.check_attempt_id, job["task_id"], job["task_id"], job["task_id"]),
                conn=conn,
            )
    return await get_turn(owner, course_id, lesson_id, saved_id)


async def retry_turn(actor, course_id, lesson_id, turn_id, key):
    require_enabled()
    owner = actor.owner_id
    _, lesson, scope = await authorized_lesson(owner, course_id, lesson_id)
    row = await owned_turn(owner, course_id, lesson_id, turn_id)
    check_lesson_version(lesson, row["content_version"])
    request_hash = digest(dump(dict(operation="retry_turn", course_id=course_id, lesson_id=lesson_id,
                                    turn_id=turn_id, content_version=row["content_version"])))
    old = await job_service.existing_job(owner, "course_tutor", key, request_hash)
    if old:
        return await get_turn(owner, course_id, lesson_id, turn_id)
    request = _request(course_id, lesson_id, turn_id, row["content_version"], scope)
    async with transaction() as conn:
        job = await job_service.enqueue_job(
            owner, "course_tutor", request, key, scope=scope.model_dump(mode="json"),
            request_hash=request_hash, conn=conn,
        )
        _, lesson, saved_scope = await authorized_lesson(
            owner, course_id, lesson_id, row["content_version"], conn=conn, lock=True
        )
        if saved_scope != scope:
            raise conflict("course_scope_changed", "课程来源已发生变化")
        row = await owned_turn(owner, course_id, lesson_id, turn_id, conn=conn, lock=True)
        if row["last_task_id"] != job["task_id"]:
            last = await course_read.task_view(owner, row["last_task_id"], course_id, lesson_id, conn=conn)
            if row["response_json"] is not None or last["status"] not in {"failed", "cancelled"}:
                raise conflict("course_tutor_retry_unavailable", "只能重试失败或已取消的助教回答")
            await _ensure_no_active_turn(
                owner, course_id, lesson_id, row["content_version"], conn=conn, excluding=turn_id
            )
            await execute(
                "UPDATE learning_course_tutor_turns SET last_task_id=%s,active_task_id=%s,updated_at=%s "
                "WHERE turn_id=%s AND owner_id=%s AND response_json IS NULL",
                (job["task_id"], job["task_id"], now(), turn_id, owner), conn=conn,
            )
    return await get_turn(owner, course_id, lesson_id, turn_id)


async def read_turn_evidence(owner, course_id, lesson_id, turn_id, source_ref):
    course, lesson, scope = await authorized_lesson(owner, course_id, lesson_id)
    row = await owned_turn(owner, course_id, lesson_id, turn_id)
    check_lesson_version(lesson, row["content_version"])
    view = await _turn_view(row)
    source = next((s for s in view["sources"] if s["source_ref"] == source_ref), None)
    raw = load(row["evidence_json"], {}).get(source_ref)
    if not source or not raw:
        raise not_found()
    item = DocumentEvidence.model_validate(raw)
    if (source.get("evidence_id") != item.evidence_id
            or source.get("document_version_id") != item.document_version_id
            or not evidence_in_scope(item, scope)):
        raise not_found()
    manifest = next((s for s in scope.documents if s.doc_id == item.doc_id), None)
    if not manifest:
        raise not_found()
    canonical = source_service.artifacts().load_canonical(manifest.canonical_artifact_key)
    if (canonical.source_sha256 != item.locator.source_sha256
            or canonical.parse_artifact_id != item.parse_artifact_id
            or canonical.canonical_text_hash != item.locator.canonical_text_hash
            or canonical.text[item.locator.start_char:item.locator.end_char] != item.excerpt):
        raise not_found()
    await course_read.authorize_course(course)
    return dict(source_ref=source_ref, title=item.title, excerpt=item.excerpt, doc_id=item.doc_id,
                document_version_id=item.document_version_id, locator=item.locator)


async def purge_course_tutor(conn, owner, course_id):
    """Tombstone inputs and derived text after source revocation has cancelled jobs."""
    stamp = now()
    await execute(
        "UPDATE learning_course_tutor_turns SET question=NULL,response_json=NULL,evidence_json=NULL,"
        "active_task_id=NULL,revoked_at=COALESCE(revoked_at,%s),updated_at=%s WHERE owner_id=%s AND course_id=%s",
        (stamp, stamp, owner, course_id), conn=conn,
    )
    await execute(
        "UPDATE learning_course_check_attempts SET answer_json=NULL,revoked_at=COALESCE(revoked_at,%s) "
        "WHERE owner_id=%s AND course_id=%s", (stamp, owner, course_id), conn=conn,
    )
