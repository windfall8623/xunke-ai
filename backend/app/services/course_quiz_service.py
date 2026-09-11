"""Course checks reuse the existing quiz queue, answers and settlement service."""

from app.core.db import execute, fetch_all, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load, uid
from app.models.course import CourseQuizCreate, CourseQuizLinkView
from app.rag.contracts import QuizSpec, ResolvedScope
from app.services import course_read, job_service, quiz_service


class _ReuseLink(Exception):
    """Roll back a racing queue insert before returning the existing check."""

    def __init__(self, link_id):
        self.link_id = link_id


async def _link_rows(owner, course_id, lesson_id=None, *, conn=None, lock=False):
    clause = " AND link.lesson_id=%s" if lesson_id is not None else ""
    args = (owner, course_id, lesson_id) if lesson_id is not None else (owner, course_id)
    return await fetch_all(
        "SELECT link.*,task.status AS task_status,task.stage AS task_stage,"
        "task.error_code AS task_error_code,task.error_message AS task_error_message,"
        "quiz.quiz_id,quiz.status AS quiz_status,quiz.settled_at,"
        "JSON_LENGTH(quiz.questions_json) AS question_count "
        "FROM learning_course_quiz_links link "
        "JOIN quiz_tasks task ON task.task_id=link.task_id AND task.user_id=link.owner_id "
        "AND task.kind='quiz' AND task.mode='production' "
        "LEFT JOIN quiz_sessions quiz ON task.status='completed' "
        "AND quiz.quiz_id=task.quiz_id AND quiz.user_id=link.owner_id "
        "AND quiz.origin_task_id=task.task_id "
        "WHERE link.owner_id=%s AND link.course_id=%s" + clause
        + " ORDER BY link.created_at,link.link_id"
        + (" FOR UPDATE" if lock else ""),
        args,
        conn=conn,
    )


def _link_view(row):
    # A queue task reserves a quiz ID before publication. Never expose that ID
    # or the private task result while there is no completed, published quiz.
    return CourseQuizLinkView(
        link_id=row["link_id"],
        lesson_id=row["lesson_id"],
        kind=row["kind"],
        parent_link_id=row["parent_link_id"],
        content_version=row["content_version"],
        created_at=iso(row["created_at"]),
        task={
            "task_id": row["task_id"],
            "quiz_id": row["quiz_id"] if row["task_status"] == "completed" else None,
            "status": row["task_status"],
            "stage": row["task_stage"],
            "error_code": row["task_error_code"],
            "error_message": row["task_error_message"],
            "result": None,
        },
    ).model_dump(mode="json")


async def list_quiz_links(owner, course_id, lesson_id, *, conn=None):
    course = await course_read.owned_course(owner, course_id, conn=conn)
    await course_read.owned_lesson(owner, course_id, lesson_id, conn=conn)
    await course_read.authorize_course(course, conn=conn)
    rows = await _link_rows(owner, course_id, lesson_id, conn=conn)
    return [_link_view(row) for row in rows]


def _check_lesson(lesson, body):
    if lesson["status"] != "ready" or not lesson["content_json"]:
        raise conflict("course_lesson_not_ready", "请先生成并阅读本课内容")
    if lesson["content_version"] != body.expected_content_version:
        raise conflict("revision_conflict", "课时内容版本已变化，请刷新后重试")


def _initial_spec(course, lesson):
    unit = load(lesson["unit_json"], {})
    payload = load(lesson["content_json"], {}).get("payload") or {}
    objective = (payload.get("objective") or unit.get("objective") or "").strip()
    blocks = payload.get("blocks", [])
    recap = "\n".join(block["text"] for block in blocks if block["type"] == "recap")
    # Recap blocks are optional in the lesson contract. Use its explanations
    # when absent, never a broad course-level syllabus.
    if not recap:
        recap = "\n".join(
            block["text"] for block in blocks if block["type"] == "explanation"
        )
    if not objective or not recap:
        raise conflict("course_lesson_scope_missing", "本课缺少可用于出题的讲解要点")
    course_spec = load(course["spec_json"], {})
    prefix = (
        "仅检查下面这节课已经讲过的目标与要点，不引入其他课时内容。\n"
        f"课程主题：{course_spec.get('topic', '')[:180]}\n"
        f"课时：{unit.get('title', '')[:200]}\n"
        f"本课目标：{objective[:700]}\n已讲要点：\n"
    )
    return QuizSpec(
        user_input=prefix + recap[: 2000 - len(prefix)],
        objective_titles=[objective],
        question_count=3,
        difficulty="mixed",
        source_policy=course["source_policy"],
        scope=load(course["requested_scope_json"])
        if course["source_policy"] == "strict_docs"
        else None,
    )


def _reusable_link(rows, body):
    current = [
        row for row in rows if row["content_version"] == body.expected_content_version
    ]
    for row in current:
        if row["task_status"] in {"pending", "running"} or (
            row["task_status"] == "completed"
            and (not row["quiz_id"] or row["quiz_status"] != "settled")
        ):
            return row
    if body.kind == "initial":
        return next(
            (
                row for row in current
                if row["kind"] == "initial" and row["task_status"] == "completed"
            ),
            None,
        )
    return None


async def _prepare_request(actor, course, lesson, body, scope, rows, *, conn=None):
    if body.kind == "initial":
        return quiz_service.resolved_quiz_request(
            actor, _initial_spec(course, lesson), scope
        )
    parent = next((row for row in rows if row["link_id"] == body.parent_link_id), None)
    if not parent:
        raise not_found()
    if parent["content_version"] != body.expected_content_version:
        raise conflict("revision_conflict", "补练来源不是当前课时版本")
    if not parent["quiz_id"] or parent["quiz_status"] != "settled" or not parent["settled_at"]:
        raise conflict("quiz_incomplete", "请先完成并结算原练习后再练错题")
    spec, review_scope, request = await quiz_service.resolved_review_request(
        actor, parent["quiz_id"], 3, "mixed", conn=conn
    )
    if review_scope != scope or spec.source_policy != course["source_policy"]:
        raise conflict("course_quiz_scope_changed", "原练习与课程的资料范围不一致")
    return spec, review_scope, request


async def create_quiz(actor, course_id, lesson_id, body: CourseQuizCreate, key):
    if not key or len(key) > 128:
        raise AppError(422, "idempotency_required", "需要有效 Idempotency-Key")
    owner = actor.owner_id
    course = await course_read.owned_course(owner, course_id)
    lesson = await course_read.owned_lesson(owner, course_id, lesson_id)
    scope = await course_read.authorize_course(course)
    request_hash = digest(dump({
        "operation": "course.lesson.quiz",
        "course_id": course_id,
        "lesson_id": lesson_id,
        "body": body.model_dump(mode="json"),
    }))
    old = await job_service.existing_job(owner, "quiz", key, request_hash)
    rows = await _link_rows(owner, course_id, lesson_id)
    if old:
        saved = next((row for row in rows if row["task_id"] == old["task_id"]), None)
        if not saved:
            raise conflict("course_quiz_link_missing", "练习任务缺少本课关联，请刷新后重试")
        return _link_view(saved)
    _check_lesson(lesson, body)
    _, scope, request = await _prepare_request(
        actor, course, lesson, body, scope, rows
    )
    reusable = _reusable_link(rows, body)
    if reusable:
        return _link_view(reusable)
    try:
        async with transaction() as conn:
            # Reserve the durable task before course/source locks. Publication
            # cannot see it until its course link commits in this transaction.
            await job_service.enqueue_job(
                owner, "quiz", request, key,
                scope=scope.model_dump(mode="json"),
                request_hash=request_hash, conn=conn,
            )
            job = await job_service.existing_job(
                owner, "quiz", key, request_hash, conn=conn, lock=True
            )
            current_course = await course_read.owned_course(
                owner, course_id, conn=conn, lock=True
            )
            current_lesson = await course_read.owned_lesson(
                owner, course_id, lesson_id, conn=conn, lock=True
            )
            _check_lesson(current_lesson, body)
            current_scope = await course_read.authorize_course(current_course, conn=conn)
            # A current locking read sees links committed while this request
            # waited for the lesson lock, even under REPEATABLE READ.
            rows = await _link_rows(owner, course_id, lesson_id, conn=conn, lock=True)
            saved = next((row for row in rows if row["task_id"] == job["task_id"]), None)
            if saved:
                return _link_view(saved)
            reusable = _reusable_link(rows, body)
            if reusable:
                raise _ReuseLink(reusable["link_id"])
            current_spec, current_scope, current_request = await _prepare_request(
                actor, current_course, current_lesson, body, current_scope, rows, conn=conn
            )
            saved_spec, saved_context = quiz_service.parse_quiz_request(job["request"])
            if (
                saved_context is not None or saved_spec != current_spec
                or ResolvedScope.model_validate(job["scope"]) != current_scope
                or job["request"] != current_request
            ):
                raise conflict("revision_conflict", "课时练习内容已变化，请刷新后重试")
            link_id = uid("cql")
            await execute(
                "INSERT INTO learning_course_quiz_links "
                "(link_id,course_id,lesson_id,owner_id,task_id,kind,parent_link_id,content_version) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (link_id, course_id, lesson_id, owner, job["task_id"], body.kind,
                 body.parent_link_id, body.expected_content_version),
                conn=conn,
            )
            rows = await _link_rows(owner, course_id, lesson_id, conn=conn, lock=True)
            return _link_view(next(row for row in rows if row["link_id"] == link_id))
    except _ReuseLink as replay:
        links = await list_quiz_links(owner, course_id, lesson_id)
        return next(link for link in links if link["link_id"] == replay.link_id)


start_lesson_quiz = create_quiz
