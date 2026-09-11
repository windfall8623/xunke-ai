"""Owner-scoped course views; revoked materials are removed before serialization."""

from app.core.db import execute, fetch_all, fetch_one
from app.core.errors import AppError, not_found
from app.core.values import iso, load, now
from app.models.sources import PublicResolvedScope
from app.rag.contracts import DocumentEvidence, ResolvedScope
from app.rag.errors import ScopeRevoked, SourceUnavailable
from app.rag.scope import evidence_in_scope
from app.services import source_service

TERMINAL = {"completed", "failed", "cancelled"}


async def owned_course(owner, course_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM learning_courses WHERE course_id=%s AND owner_id=%s"
        + (" FOR UPDATE" if lock else ""), (course_id, owner), conn=conn,
    )
    if not row:
        raise not_found()
    return row


async def owned_lesson(owner, course_id, lesson_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM learning_course_lessons WHERE lesson_id=%s AND course_id=%s AND owner_id=%s"
        + (" FOR UPDATE" if lock else ""), (lesson_id, course_id, owner), conn=conn,
    )
    if not row:
        raise not_found()
    return row


async def authorize_course(row, *, conn=None):
    if row["status"] == "source_revoked" or not row["resolved_scope_json"]:
        raise AppError(404, "source_revoked", "课程关联资料已失效，请重新选择资料创建课程")
    scope = ResolvedScope.model_validate(load(row["resolved_scope_json"]))
    if scope.owner_id != row["owner_id"] or scope.namespace != "production" or scope.fingerprint != row["scope_fingerprint"]:
        raise not_found()
    if (row["source_policy"] == "strict_docs") != bool(scope.documents):
        raise not_found()
    try:
        await source_service.reauthorize_scope(scope, conn=conn)
    except (ScopeRevoked, SourceUnavailable) as exc:
        raise AppError(404, "source_revoked", "课程关联资料已删除或授权已变更") from exc
    return scope


async def task_view(owner, task_id, course_id, lesson_id=None, *, conn=None):
    if not task_id:
        return None
    task = await fetch_one(
        "SELECT task_id,kind,status,stage,error_code FROM quiz_tasks "
        "WHERE task_id=%s AND user_id=%s AND mode='production' AND kind IN ('course_outline','course_lesson')",
        (task_id, owner), conn=conn,
    )
    if not task:
        raise not_found()
    errors = {
        "deadline_exceeded": "生成超时，请稍后重试或缩小课程范围",
        "course_scope_too_large": "所选资料范围过大，请减少资料或选择具体章节",
        "course_material_gap": "资料不足以支持本课，请补充资料后创建课程",
        "course_provider_unavailable": "课程模型暂未配置，请检查模型设置",
        "course_generation_invalid": "模型返回的课程格式不完整，请重试",
        "course_disabled": "课程生成功能暂未启用",
        "source_revoked": "关联资料已失效",
    }
    return dict(
        **task, course_id=course_id, lesson_id=lesson_id,
        error_message=errors.get(task["error_code"], "生成未完成，请稍后重试") if task["error_code"] else None,
    )


def current_status(row, task):
    if row["status"] == "generating" and task and task["status"] in {"failed", "cancelled"}:
        return task["status"]
    return row["status"]


async def course_view(row):
    try:
        scope = await authorize_course(row)
    except AppError as exc:
        if exc.code != "source_revoked":
            raise
        return dict(
            course_id=row["course_id"], title="资料已失效的课程", source_policy=row["source_policy"],
            source_status="revoked", status="source_revoked", revision=row["revision"],
            created_at=iso(row["created_at"]), updated_at=iso(row["updated_at"]),
            warnings=["关联资料已失效，课程内容不再显示"],
        )
    outline = load(row["outline_json"], {})
    payload = outline.get("payload") or {}
    spec = load(row["spec_json"], {})
    lessons = await fetch_all(
        "SELECT * FROM learning_course_lessons WHERE course_id=%s AND owner_id=%s ORDER BY position",
        (row["course_id"], row["owner_id"]),
    )
    summaries = []
    for lesson in lessons:
        task = await task_view(row["owner_id"], lesson["generation_task_id"], row["course_id"], lesson["lesson_id"])
        summaries.append(dict(
            **load(lesson["unit_json"], {}), lesson_id=lesson["lesson_id"], position=lesson["position"],
            status=current_status(lesson, task), revision=lesson["revision"], content_version=lesson["content_version"],
            read_at=iso(lesson["read_at"]), last_opened_at=iso(lesson["last_opened_at"]),
        ))
    task = await task_view(row["owner_id"], row["outline_task_id"], row["course_id"])
    available = [l for l in lessons if l["status"] != "material_gap"]
    opened = sorted([l for l in available if l["last_opened_at"]], key=lambda l: l["last_opened_at"], reverse=True)
    resume = next((l["lesson_id"] for l in opened if not l["read_at"]), None)
    resume = resume or next((l["lesson_id"] for l in available if not l["read_at"]), None)
    resume = resume or (opened[0]["lesson_id"] if opened else None)
    # Recheck after reading potentially large derived content.
    await authorize_course(row)
    return dict(
        course_id=row["course_id"], title=payload.get("title") or spec.get("topic", "新课程"),
        source_policy=row["source_policy"], source_status="active",
        scope=PublicResolvedScope.from_scope(scope) if scope.documents else None,
        status=current_status(row, task), revision=row["revision"], mission=payload.get("mission"),
        lessons=summaries, sources=outline.get("sources", []), latest_task=task,
        active_task=task if task and task["status"] not in TERMINAL else None,
        resume_lesson_id=resume,
        outline_editable=bool(payload) and not any(l["generation_task_id"] for l in lessons),
        warnings=outline.get("warnings", []) + outline.get("assumptions", []),
        created_at=iso(row["created_at"]), updated_at=iso(row["updated_at"]),
    )


async def get_course(owner, course_id):
    return await course_view(await owned_course(owner, course_id))


async def list_courses(owner, page=1, page_size=20):
    count = await fetch_one("SELECT COUNT(*) AS n FROM learning_courses WHERE owner_id=%s", (owner,))
    rows = await fetch_all(
        "SELECT * FROM learning_courses WHERE owner_id=%s ORDER BY updated_at DESC,course_id DESC LIMIT %s OFFSET %s",
        (owner, page_size, (page - 1) * page_size),
    )
    return dict(items=[await course_view(row) for row in rows], total=count["n"], page=page, page_size=page_size)


async def get_lesson(owner, course_id, lesson_id, *, opened=False):
    from app.services.course_quiz_service import list_quiz_links

    course = await owned_course(owner, course_id)
    await authorize_course(course)
    row = await owned_lesson(owner, course_id, lesson_id)
    if opened:
        stamp = now()
        await execute(
            "UPDATE learning_course_lessons SET last_opened_at=%s WHERE lesson_id=%s AND owner_id=%s",
            (stamp, lesson_id, owner),
        )
        row["last_opened_at"] = stamp
    unit = load(row["unit_json"], {})
    content = load(row["content_json"], {})
    payload = content.get("payload") or {}
    task = await task_view(owner, row["generation_task_id"], course_id, lesson_id)
    links = await list_quiz_links(owner, course_id, lesson_id)
    await authorize_course(course)
    return dict(
        lesson_id=lesson_id, course_id=course_id, title=unit.get("title", "课时"),
        objective=unit.get("objective"), estimated_minutes=unit.get("estimated_minutes"),
        status=current_status(row, task), revision=row["revision"], content_version=row["content_version"],
        blocks=payload.get("blocks", []), checks=payload.get("checks", []), next_step=payload.get("next_step"),
        sources=content.get("sources", []), warnings=content.get("warnings", []),
        read_at=iso(row["read_at"]), last_opened_at=iso(row["last_opened_at"]),
        latest_task=task, active_task=task if task and task["status"] not in TERMINAL else None, quiz_links=links,
    )


async def get_task(owner, task_id):
    task = await fetch_one(
        "SELECT kind,request_json FROM quiz_tasks WHERE task_id=%s AND user_id=%s "
        "AND kind IN ('course_outline','course_lesson') AND mode='production'", (task_id, owner),
    )
    if not task:
        raise not_found()
    request = load(task["request_json"], {})
    course_id, lesson_id = request.get("course_id"), request.get("lesson_id")
    if not course_id:
        raise AppError(404, "source_revoked", "课程任务来源已失效")
    course = await owned_course(owner, course_id)
    await authorize_course(course)
    if task["kind"] == "course_lesson":
        await owned_lesson(owner, course_id, lesson_id)
    return await task_view(owner, task_id, course_id, lesson_id)


async def read_evidence(owner, course_id, source_ref, lesson_id=None):
    course = await owned_course(owner, course_id)
    scope = await authorize_course(course)
    row = await owned_lesson(owner, course_id, lesson_id) if lesson_id else course
    draft = load(row["content_json" if lesson_id else "outline_json"], {})
    source = next((s for s in draft.get("sources", []) if s["source_ref"] == source_ref), None)
    raw = load(row["evidence_json"], {}).get(source_ref)
    if not source or not raw:
        raise not_found()
    item = DocumentEvidence.model_validate(raw)
    if source.get("evidence_id") != item.evidence_id or not evidence_in_scope(item, scope):
        raise not_found()
    manifest = next((s for s in scope.documents if s.doc_id == item.doc_id), None)
    if not manifest:
        raise not_found()
    canonical = source_service.artifacts().load_canonical(manifest.canonical_artifact_key)
    if (
        canonical.source_sha256 != item.locator.source_sha256
        or canonical.parse_artifact_id != item.parse_artifact_id
        or canonical.canonical_text_hash != item.locator.canonical_text_hash
        or canonical.text[item.locator.start_char:item.locator.end_char] != item.excerpt
    ):
        raise not_found()
    await authorize_course(course)
    return dict(source_ref=source_ref, title=item.title, excerpt=item.excerpt,
                doc_id=item.doc_id, document_version_id=item.document_version_id, locator=item.locator)
