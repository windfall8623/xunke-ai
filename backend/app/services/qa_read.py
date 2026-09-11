"""Authorized QA views. Never return a revoked artifact for client-side hiding."""

from pydantic import ValidationError

from app.core.db import fetch_all, fetch_one
from app.core.errors import AppError, not_found
from app.core.values import digest, dump, iso, load, now
from app.models.sources import PublicResolvedScope
from app.qa.contracts import ChatAnswerArtifact
from app.rag.contracts import ResolvedScope, Usage
from app.rag.errors import ScopeRevoked, SourceUnavailable
from app.rag.scope import evidence_in_scope
from app.services import source_service

REVOKED_TEXT = "关联资料已删除或授权已变更，此轮内容不再显示。"


async def owned_session(owner, session_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM qa_sessions WHERE session_id=%s AND owner_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (session_id, owner),
        conn=conn,
    )
    if not row:
        raise not_found()
    return row


async def revision_scope(owner, session_id, revision, *, conn=None):
    row = await fetch_one(
        "SELECT scope_json,scope_fingerprint FROM qa_scope_revisions "
        "WHERE session_id=%s AND revision=%s AND owner_id=%s",
        (session_id, revision, owner),
        conn=conn,
    )
    if not row:
        raise not_found()
    scope = ResolvedScope.model_validate(load(row["scope_json"]))
    if (
        scope.owner_id != owner
        or scope.namespace != "production"
        or scope.fingerprint != row["scope_fingerprint"]
    ):
        raise not_found()
    return scope


async def scope_available(scope, *, conn=None):
    try:
        await source_service.reauthorize_scope(scope, conn=conn)
        return True
    except (ScopeRevoked, SourceUnavailable):
        return False


async def require_source(scope, *, conn=None):
    if not await scope_available(scope, conn=conn):
        raise AppError(404, "source_revoked", "关联资料已删除或授权已变更")


async def active_task(row, *, conn=None):
    if not row["active_task_id"]:
        return None
    task = await fetch_one(
        "SELECT task_id FROM quiz_tasks WHERE task_id=%s AND user_id=%s AND kind='qa' "
        "AND status IN ('pending','running')",
        (row["active_task_id"], row["owner_id"]),
        conn=conn,
    )
    return task["task_id"] if task else None


async def session_view(row):
    scope = await revision_scope(
        row["owner_id"], row["session_id"], row["scope_revision"]
    )
    available = await scope_available(scope)
    return dict(
        session_id=row["session_id"],
        title=row["title"] if available else "资料已失效的会话",
        scope_revision=row["scope_revision"],
        scope=PublicResolvedScope.from_scope(scope) if available else None,
        source_status="active" if available else "revoked",
        active_task_id=await active_task(row) if available else None,
        created_at=iso(row["created_at"]),
        updated_at=iso(row["updated_at"]),
    )


async def get_session(owner, session_id):
    return await session_view(await owned_session(owner, session_id))


async def list_sessions(owner, page, page_size):
    count = await fetch_one(
        "SELECT COUNT(*) AS n FROM qa_sessions WHERE owner_id=%s", (owner,)
    )
    rows = await fetch_all(
        "SELECT * FROM qa_sessions WHERE owner_id=%s ORDER BY updated_at DESC,session_id DESC LIMIT %s OFFSET %s",
        (owner, page_size, (page - 1) * page_size),
    )
    return dict(
        items=[await session_view(row) for row in rows],
        total=count["n"],
        page=page,
        page_size=page_size,
    )


def checked_artifact(row, scope):
    raw = load(row["artifact_json"])
    if not raw or digest(dump(raw)) != row["artifact_hash"]:
        raise not_found()
    try:
        artifact = ChatAnswerArtifact.model_validate(
            {
                **raw,
                "usage": {
                    k: v
                    for k, v in raw.get("usage", {}).items()
                    if k in Usage.model_fields
                },
            }
        )
    except (ValidationError, TypeError, ValueError) as exc:
        raise not_found() from exc
    if artifact.scope_fingerprint != scope.fingerprint or any(
        not evidence_in_scope(e, scope) for e in artifact.evidence
    ):
        raise not_found()
    return artifact


def answer_view(row, scope):
    artifact = checked_artifact(row, scope)
    return dict(
        answer_id=row["answer_id"],
        session_id=row["session_id"],
        message_id=row["message_id"],
        scope_revision=row["scope_revision"],
        answer_status=artifact.answer_status,
        blocks=[block.model_dump(mode="json") for block in artifact.blocks],
        evidence=[item.model_dump(mode="json") for item in artifact.evidence],
        retrieval_query=artifact.retrieval_query,
        usage=load(row["usage_json"], {}),
        created_at=iso(row["created_at"]),
    )


async def owned_answer(owner, answer_id, *, conn=None):
    row = await fetch_one(
        "SELECT * FROM qa_answers WHERE answer_id=%s AND owner_id=%s",
        (answer_id, owner),
        conn=conn,
    )
    if not row:
        raise not_found()
    scope = await revision_scope(
        owner, row["session_id"], row["scope_revision"], conn=conn
    )
    await require_source(scope, conn=conn)
    return row, scope


async def get_messages(owner, session_id, before_sequence=None, page_size=30):
    await owned_session(owner, session_id)
    args = [session_id, owner]
    cursor = ""
    if before_sequence is not None:
        cursor = " AND m.sequence<%s"
        args.append(before_sequence)
    args.append(page_size + 1)
    rows = await fetch_all(
        "SELECT m.*,t.status AS task_status,t.error_code AS task_error FROM qa_messages m "
        "JOIN quiz_tasks t ON t.task_id=m.task_id AND t.user_id=m.owner_id "
        "WHERE m.session_id=%s AND m.owner_id=%s"
        + cursor
        + " ORDER BY m.sequence DESC LIMIT %s",
        args,
    )
    has_more = len(rows) > page_size
    selected = list(reversed(rows[:page_size]))
    scopes, items = {}, []
    for row in selected:
        revision = row["scope_revision"]
        if revision not in scopes:
            scope = await revision_scope(owner, session_id, revision)
            scopes[revision] = (scope, await scope_available(scope))
        scope, available = scopes[revision]
        answer = None
        status = (
            "revoked"
            if not available
            else "completed"
            if row["role"] == "user"
            else row["task_status"]
        )
        content = row["content"] if available else REVOKED_TEXT
        if available and row["role"] == "assistant" and status == "completed":
            saved = await fetch_one(
                "SELECT * FROM qa_answers WHERE message_id=%s AND owner_id=%s",
                (row["message_id"], owner),
            )
            if not saved:
                raise not_found()
            answer = answer_view(saved, scope)
            content = "\n\n".join(block["text"] for block in answer["blocks"])
        items.append(
            dict(
                message_id=row["message_id"],
                session_id=session_id,
                sequence=row["sequence"],
                role=row["role"],
                content=content,
                scope_revision=revision,
                task_id=row["task_id"],
                status=status,
                answer=answer,
                error_code=row["task_error"]
                if available and row["role"] == "assistant"
                else None,
                created_at=iso(row["created_at"]),
            )
        )
    return dict(
        items=items,
        has_more=has_more,
        next_before=selected[0]["sequence"] if has_more else None,
    )


async def get_task(owner, task_id):
    row = await fetch_one(
        "SELECT t.*,m.message_id,m.session_id,m.scope_revision,m.created_at AS message_created_at,"
        "m.started_at,m.finished_at FROM quiz_tasks t JOIN qa_messages m ON m.task_id=t.task_id "
        "AND m.owner_id=t.user_id AND m.role='assistant' WHERE t.task_id=%s AND t.user_id=%s "
        "AND t.kind='qa' AND t.mode='production'",
        (task_id, owner),
    )
    if not row:
        raise not_found()
    scope = await revision_scope(owner, row["session_id"], row["scope_revision"])
    await require_source(scope)
    answer = None
    if row["status"] == "completed":
        saved = await fetch_one(
            "SELECT * FROM qa_answers WHERE task_id=%s AND owner_id=%s",
            (task_id, owner),
        )
        if not saved:
            raise not_found()
        answer = answer_view(saved, scope)
    started, finished = row["started_at"], row["finished_at"]
    queue_ms = max(
        0,
        int(
            ((started or finished or now()) - row["message_created_at"]).total_seconds()
            * 1000
        ),
    )
    execution_ms = (
        max(0, int(((finished or now()) - started).total_seconds() * 1000))
        if started
        else None
    )
    return dict(
        task_id=task_id,
        session_id=row["session_id"],
        message_id=row["message_id"],
        status=row["status"],
        stage=row["stage"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        answer=answer,
        queue_ms=queue_ms,
        execution_ms=execution_ms,
    )


async def read_evidence(owner, answer_id, evidence_id):
    row, scope = await owned_answer(owner, answer_id)
    artifact = checked_artifact(row, scope)
    item = next((e for e in artifact.evidence if e.evidence_id == evidence_id), None)
    if item is None:
        raise not_found()
    source = next((s for s in scope.documents if s.doc_id == item.doc_id), None)
    if source is None:
        raise not_found()
    canonical = source_service.artifacts().load_canonical(source.canonical_artifact_key)
    if (
        canonical.source_sha256 != item.locator.source_sha256
        or canonical.parse_artifact_id != item.parse_artifact_id
        or canonical.canonical_text_hash != item.locator.canonical_text_hash
        or canonical.text[item.locator.start_char : item.locator.end_char]
        != item.excerpt
    ):
        raise not_found()
    await require_source(scope)
    return item
