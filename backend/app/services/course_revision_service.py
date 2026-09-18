"""Limited course revisions: preview, candidate generation and atomic apply (B06).

一次修订最多三节课；预览不调用模型；确认发布是原子事务——旧正文先快照，
新正文 content_version+1，read_at 清空但历史可回看。未完成候选、过时预览
或进行中的课时生成都阻止发布。
"""

from datetime import UTC, datetime

from pydantic import TypeAdapter, ValidationError

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, load, now, uid
from app.models.course import CourseLessonGenerate, CourseRevisionGenerate, CourseRevisionPreview, CourseRevisionView

MAX_REVISION_LESSONS = 3


def revision_can_apply(*, current_course_revision, expected_course_revision,
                       current_versions, frozen_versions, all_drafts_ready,
                       any_active_lesson_generation):
    return (
        current_course_revision == expected_course_revision
        and current_versions == frozen_versions
        and all_drafts_ready
        and not any_active_lesson_generation
    )


def _request_view(row) -> CourseRevisionView:
    selection = load(row["selection_json"], {})
    return CourseRevisionView(
        revision_id=row["revision_id"],
        course_id=row["course_id"],
        revision=row["revision"],
        status=row["status"],
        expected_course_revision=row["expected_course_revision"],
        lessons=[
            {
                "lesson_id": item["lesson_id"],
                "previous_content_version": item["expected_content_version"],
                "instruction": item["instruction"],
            }
            for item in selection.get("lessons", [])
        ],
        impacts=load(row["impact_json"], []) or [],
        candidates=load(row["candidates_json"], []) or [],
        error_code=row["error_code"],
    )


async def _owned_request(owner, course_id, revision_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM learning_course_revision_requests WHERE revision_id=%s "
        "AND course_id=%s AND owner_id=%s" + (" FOR UPDATE" if lock else ""),
        (revision_id, course_id, owner),
        conn=conn,
    )
    if row is None:
        raise not_found()
    return row


async def create_revision_preview(actor, course_id, body: CourseRevisionPreview, key):
    from app.services import course_read

    owner = actor.owner_id
    request_hash = digest(dump({"course_id": course_id, **body.model_dump(mode="json")}))
    async with transaction() as conn:
        existing = await fetch_one(
            "SELECT * FROM learning_course_revision_requests WHERE owner_id=%s "
            "AND idempotency_key=%s",
            (owner, key), conn=conn,
        )
        if existing and existing["request_hash"] == request_hash:
            return _request_view(existing)
        if existing:
            raise conflict("idempotency_conflict", "相同操作标识已用于不同请求")
        course = await course_read.owned_course(owner, course_id, conn=conn, lock=True)
        await course_read.authorize_course(course, conn=conn)
        if course["revision"] != body.expected_course_revision:
            raise conflict("revision_conflict", "课程状态已更新，请刷新后重试")
        if len(body.lessons) > MAX_REVISION_LESSONS:
            raise AppError(422, "revision_scope_too_large", "一次最多修订三节课")
        lessons = {item.lesson_id: item for item in body.lessons}
        impacts = []
        for lesson in await fetch_all(
            "SELECT * FROM learning_course_lessons WHERE owner_id=%s AND course_id=%s",
            (owner, course_id), conn=conn,
        ):
            item = lessons.get(lesson["lesson_id"])
            if not item:
                continue
            if int(lesson["content_version"]) != item.expected_content_version:
                raise conflict("revision_conflict", "所选课时已更新，请刷新后重试")
            if lesson["status"] != "ready" or not lesson["content_json"]:
                raise conflict("course_lesson_not_ready", "只有已发布课文可以修订")
            links = await fetch_all(
                "SELECT link_id FROM learning_course_quiz_links WHERE owner_id=%s AND lesson_id=%s "
                "AND content_version=%s",
                (owner, lesson["lesson_id"], lesson["content_version"]), conn=conn,
            )
            impacts.append({
                "lesson_id": lesson["lesson_id"],
                "previous_content_version": lesson["content_version"],
                "next_content_version": lesson["content_version"] + 1,
                "retained_check_count": len(links),
                "current_evidence_will_be_stale": True,
            })
        if len(impacts) != len(body.lessons):
            raise not_found()
        revision_id = uid("crev")
        await execute(
            "INSERT INTO learning_course_revision_requests(revision_id,course_id,owner_id,"
            "status,selection_json,impact_json,instruction,expected_course_revision,"
            "expected_criteria_revision,idempotency_key,request_hash) "
            "VALUES(%s,%s,%s,'preview',%s,%s,%s,%s,%s,%s,%s)",
            (revision_id, course_id, owner,
             dump({"lessons": [item.model_dump(mode="json") for item in body.lessons]}),
             dump(impacts), body.instruction or None,
             body.expected_course_revision, body.expected_criteria_revision, key, request_hash),
            conn=conn,
        )
        row = await _owned_request(owner, course_id, revision_id, conn=conn)
    return _request_view(row)


async def get_revision(owner, course_id, revision_id):
    row = await _owned_request(owner, course_id, revision_id)
    return _request_view(row)


async def mark_revision_candidate(course_id, owner_id, revision_id, lesson_id, draft, *, conn):
    """worker 发布分支：候选稿写回修订记录，不改动当前课时。"""
    row = await fetch_one(
        "SELECT * FROM learning_course_revision_requests WHERE revision_id=%s AND owner_id=%s "
        "FOR UPDATE",
        (revision_id, owner_id), conn=conn,
    )
    if row is None or row["course_id"] != course_id:
        raise not_found()
    candidates = load(row["candidates_json"], []) or []
    candidates = [item for item in candidates if item.get("lesson_id") != lesson_id]
    candidates.append({
        "lesson_id": lesson_id,
        "previous_content_version": _frozen_version(row, lesson_id),
        "draft": draft,
    })
    complete = all(
        any(item.get("lesson_id") == lesson["lesson_id"] for item in candidates)
        for lesson in load(row["selection_json"], {}).get("lessons", [])
    )
    await execute(
        "UPDATE learning_course_revision_requests SET candidates_json=%s,status=%s,revision=revision+1 "
        "WHERE revision_id=%s AND owner_id=%s",
        (dump(candidates), "ready" if complete else "generating", revision_id, owner_id),
        conn=conn,
    )


def _frozen_version(row, lesson_id):
    for item in load(row["selection_json"], {}).get("lessons", []):
        if item.get("lesson_id") == lesson_id:
            return item.get("expected_content_version")
    return None


async def snapshot_lesson(conn, owner, course_id, lesson_id):
    lesson = await fetch_one(
        "SELECT * FROM learning_course_lessons WHERE lesson_id=%s AND course_id=%s AND owner_id=%s",
        (lesson_id, course_id, owner), conn=conn,
    )
    if lesson is None or not lesson["content_json"]:
        return
    await execute(
        "INSERT INTO learning_course_lesson_snapshots(snapshot_id,lesson_id,course_id,owner_id,"
        "content_version,content_json,evidence_json,read_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE snapshot_id=snapshot_id",
        (uid("snap"), lesson_id, course_id, owner, lesson["content_version"],
         lesson["content_json"], lesson["evidence_json"], lesson["read_at"]),
        conn=conn,
    )


async def apply_revision(actor, course_id, revision_id, body, key):
    from app.services import course_read

    owner = actor.owner_id
    async with transaction() as conn:
        course = await course_read.owned_course(owner, course_id, conn=conn, lock=True)
        await course_read.authorize_course(course, conn=conn)
        request_row = await _owned_request(owner, course_id, revision_id, conn=conn, lock=True)
        if request_row["status"] == "applied":
            return _request_view(request_row)
        if request_row["status"] != "ready":
            raise conflict("revision_not_ready", "候选稿尚未全部完成")
        if request_row["revision"] != body.expected_revision:
            raise conflict("revision_conflict", "修订状态已更新，请刷新后重试")
        if course["revision"] != body.expected_course_revision:
            raise conflict("revision_conflict", "课程状态已更新，请刷新后重试")
        selection = load(request_row["selection_json"], {}).get("lessons", [])
        candidates = {
            item["lesson_id"]: item["draft"] for item in load(request_row["candidates_json"], [])
        }
        current_versions, frozen_versions = {}, {}
        any_active = False
        for item in selection:
            lesson_id = item["lesson_id"]
            lesson = await fetch_one(
                "SELECT * FROM learning_course_lessons WHERE lesson_id=%s AND owner_id=%s",
                (lesson_id, owner), conn=conn,
            )
            current_versions[lesson_id] = lesson["content_version"]
            frozen_versions[lesson_id] = item["expected_content_version"]
            if lesson["active_task_id"]:
                any_active = True
        if not revision_can_apply(
            current_course_revision=course["revision"],
            expected_course_revision=body.expected_course_revision,
            current_versions=current_versions,
            frozen_versions=frozen_versions,
            all_drafts_ready=set(candidates) == set(current_versions),
            any_active_lesson_generation=any_active,
        ):
            raise conflict("revision_conflict", "课程或课时已变化，请重新预览后再发布")
        stamp = now()
        for lesson_id, draft in candidates.items():
            await snapshot_lesson(conn, owner, course_id, lesson_id)
        for lesson_id, draft in candidates.items():
            await execute(
                "UPDATE learning_course_lessons SET content_json=%s,status='ready',"
                "active_task_id=NULL,content_version=content_version+1,revision=revision+1,"
                "read_at=NULL,updated_at=%s WHERE lesson_id=%s AND owner_id=%s",
                (dump(draft), stamp, lesson_id, owner), conn=conn,
            )
        await execute(
            "UPDATE learning_course_revision_requests SET status='applied',revision=revision+1 "
            "WHERE revision_id=%s AND owner_id=%s",
            (revision_id, owner), conn=conn,
        )
        await execute(
            "UPDATE learning_courses SET revision=revision+1,updated_at=%s "
            "WHERE course_id=%s AND owner_id=%s",
            (stamp, course_id, owner), conn=conn,
        )
        row = await _owned_request(owner, course_id, revision_id, conn=conn)
    return _request_view(row)


async def list_lesson_versions(owner, course_id, lesson_id):
    return [
        {
            "content_version": row["content_version"],
            "archived_at": row["archived_at"].isoformat(),
            "read_at": row["read_at"].isoformat() if row["read_at"] else None,
        }
        for row in await fetch_all(
            "SELECT content_version,archived_at,read_at FROM learning_course_lesson_snapshots "
            "WHERE owner_id=%s AND course_id=%s AND lesson_id=%s ORDER BY content_version",
            (owner, course_id, lesson_id),
        )
    ]


async def get_lesson_version(owner, course_id, lesson_id, content_version: int):
    row = await fetch_one(
        "SELECT content_json,evidence_json,content_version,read_at,archived_at "
        "FROM learning_course_lesson_snapshots WHERE owner_id=%s AND course_id=%s "
        "AND lesson_id=%s AND content_version=%s",
        (owner, course_id, lesson_id, content_version),
    )
    if row is None:
        raise not_found()
    return {
        "lesson_id": lesson_id,
        "content_version": row["content_version"],
        "content": load(row["content_json"], {}),
        "read_only": True,
        "archived_at": row["archived_at"].isoformat(),
    }


async def ensure_generating(owner, course_id, revision_id, lesson_id):
    row = await _owned_request(owner, course_id, revision_id)
    if row["status"] not in {"generating", "ready"}:
        raise conflict("revision_not_generating", "请先生成修订预览并开始修订")
    selection = load(row["selection_json"], {}).get("lessons", [])
    if not any(item.get("lesson_id") == lesson_id for item in selection):
        raise not_found()
    return row


async def start_revision_jobs(actor, course_id, body, key):
    """为所选课时建立候选稿任务；任务复用既有 course_lesson 类型。"""
    from app.services import course_service, course_teaching

    course_service.require_enabled()
    if not course_service.get_settings().enable_course_revisions:
        raise AppError(409, "course_revisions_disabled", "课程修订功能未开启")
    owner = actor.owner_id
    request_row = await _owned_request(owner, course_id, body.revision_id)
    if request_row["status"] not in {"preview", "generating", "ready"}:
        raise conflict("revision_not_generating", "该修订不能再生成候选稿")
    if request_row["revision"] != body.expected_revision:
        raise conflict("revision_conflict", "修订状态已更新，请刷新后重试")
    # Resolve the current owner's configuration before mutating the preview or
    # enqueueing any candidate; missing personal credentials never use system.
    await course_teaching.require_model(owner)
    await execute(
        "UPDATE learning_course_revision_requests SET status='generating',"
        "revision=revision+1 WHERE revision_id=%s AND owner_id=%s AND status='preview' "
        "AND revision=%s",
        (body.revision_id, owner, body.expected_revision),
    )
    tasks = []
    for item in load(request_row["selection_json"], {}).get("lessons", []):
        task = await course_service.generate_lesson(
            actor, course_id, item["lesson_id"],
            CourseLessonGenerate(
                expected_course_revision=request_row["expected_course_revision"],
                revision_id=body.revision_id,
            ),
            f"{key}:{item['lesson_id']}",
        )
        tasks.append(task)
    row = await _owned_request(owner, course_id, body.revision_id)
    return _request_view(row)
