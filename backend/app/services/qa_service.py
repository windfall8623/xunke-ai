"""Transactional QA commands. The session row serializes message ordering."""

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import conflict
from app.core.values import digest, dump, load, uid
from app.qa.contracts import ChatHistoryTurn, select_history
from app.services import job_service, qa_read, source_service


async def create_session(actor, body):
    scope = await source_service.resolve_scope(actor, body.scope)
    session_id = uid("qas")
    async with transaction() as conn:
        await qa_read.require_source(scope, conn=conn)
        await execute(
            "INSERT INTO qa_sessions(session_id,owner_id,title) VALUES(%s,%s,%s)",
            (session_id, actor.owner_id, body.title),
            conn=conn,
        )
        await execute(
            "INSERT INTO qa_scope_revisions(session_id,revision,owner_id,scope_json,scope_fingerprint) VALUES(%s,1,%s,%s,%s)",
            (session_id, actor.owner_id, dump(scope), scope.fingerprint),
            conn=conn,
        )
    return await qa_read.get_session(actor.owner_id, session_id)


async def update_scope(actor, session_id, body):
    await qa_read.owned_session(actor.owner_id, session_id)
    scope = await source_service.resolve_scope(actor, body.scope)
    async with transaction() as conn:
        session = await qa_read.owned_session(
            actor.owner_id, session_id, conn=conn, lock=True
        )
        if await qa_read.active_task(session, conn=conn):
            raise conflict("qa_session_busy", "请等待当前回答完成或先取消，再更换资料")
        if session["scope_revision"] != body.expected_revision:
            raise conflict("scope_revision_conflict", "资料范围已更新，请刷新后重试")
        await qa_read.require_source(scope, conn=conn)
        revision = session["scope_revision"] + 1
        await execute(
            "INSERT INTO qa_scope_revisions(session_id,revision,owner_id,scope_json,scope_fingerprint) VALUES(%s,%s,%s,%s,%s)",
            (session_id, revision, actor.owner_id, dump(scope), scope.fingerprint),
            conn=conn,
        )
        # The old title may quote the old scope. Do not carry derived text into a
        # new revision whose authorization no longer covers that material.
        await execute(
            "UPDATE qa_sessions SET scope_revision=%s,title='新的资料问答',updated_at=UTC_TIMESTAMP(6) WHERE session_id=%s",
            (revision, session_id),
            conn=conn,
        )
    return await qa_read.get_session(actor.owner_id, session_id)


async def create_message(actor, session_id, body, key):
    await qa_read.owned_session(actor.owner_id, session_id)
    semantic_hash = digest(
        dump({"session_id": session_id, **body.model_dump(mode="json")})
    )
    async with transaction() as conn:
        session = await qa_read.owned_session(
            actor.owner_id, session_id, conn=conn, lock=True
        )
        old = await job_service.existing_job(
            actor.owner_id, "qa", key, semantic_hash, conn=conn
        )
        if old:
            task_id = old["task_id"]
        else:
            if session["scope_revision"] != body.scope_revision:
                raise conflict(
                    "scope_revision_conflict", "资料范围已更新，请刷新后重试"
                )
            scope = await qa_read.revision_scope(
                actor.owner_id, session_id, body.scope_revision, conn=conn
            )
            await qa_read.require_source(scope, conn=conn)
            if await qa_read.active_task(session, conn=conn):
                raise conflict("qa_session_busy", "当前会话已有回答正在生成")
            from app.services.evaluation_service import pipeline_config

            config = pipeline_config(get_settings().rag_pipeline_id)
            if config.pipeline_version == "legacy-summary-b0":
                raise conflict("qa_pipeline_unavailable", "当前检索方案不支持资料问答")
            user_id, assistant_id = uid("qam"), uid("qam")
            request = dict(
                session_id=session_id,
                question=body.content,
                scope_revision=body.scope_revision,
                user_message_id=user_id,
                assistant_message_id=assistant_id,
                pipeline_config=config.model_dump(mode="json"),
            )
            job = await job_service.enqueue_job(
                actor.owner_id,
                "qa",
                request,
                key,
                scope=scope.model_dump(mode="json"),
                conn=conn,
                request_hash=semantic_hash,
            )
            task_id = job["task_id"]
            for offset, role, message_id, content in [
                (0, "user", user_id, body.content),
                (1, "assistant", assistant_id, ""),
            ]:
                await execute(
                    "INSERT INTO qa_messages(message_id,session_id,owner_id,sequence,role,content,scope_revision,task_id,status) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        message_id,
                        session_id,
                        actor.owner_id,
                        session["next_sequence"] + offset,
                        role,
                        content,
                        body.scope_revision,
                        task_id,
                        "completed" if role == "user" else "pending",
                    ),
                    conn=conn,
                )
            await execute(
                "UPDATE qa_sessions SET next_sequence=next_sequence+2,active_task_id=%s,updated_at=UTC_TIMESTAMP(6) WHERE session_id=%s",
                (task_id, session_id),
                conn=conn,
            )
    return await qa_read.get_task(actor.owner_id, task_id)


async def cancel_task(owner, task_id):
    await qa_read.get_task(owner, task_id)
    async with transaction() as conn:
        # Keep the task lock through message updates, matching publication and
        # source cleanup. A separate message-first transaction can deadlock.
        await job_service.cancel_job(owner, task_id, conn=conn)
        await execute(
            "UPDATE qa_messages m JOIN quiz_tasks t ON t.task_id=m.task_id SET m.status=t.status,"
            "m.finished_at=COALESCE(m.finished_at,UTC_TIMESTAMP(6)) WHERE m.task_id=%s AND m.owner_id=%s "
            "AND m.role='assistant' AND m.status<>'revoked' AND t.status='cancelled'",
            (task_id, owner),
            conn=conn,
        )
    return await qa_read.get_task(owner, task_id)


async def history_for_job(
    owner, session_id, revision, scope, before_sequence, *, conn=None
):
    await qa_read.require_source(scope, conn=conn)
    rows = await fetch_all(
        "SELECT a.*,u.content AS question FROM qa_answers a JOIN qa_messages m ON m.message_id=a.message_id "
        "JOIN qa_messages u ON u.task_id=a.task_id AND u.role='user' AND u.owner_id=a.owner_id "
        "WHERE a.session_id=%s AND a.owner_id=%s AND a.scope_revision=%s AND m.sequence<%s AND a.artifact_json IS NOT NULL "
        "ORDER BY m.sequence DESC LIMIT 6",
        (session_id, owner, revision, before_sequence),
        conn=conn,
    )
    turns = []
    for row in reversed(rows):
        artifact = qa_read.checked_artifact(row, scope)
        turns.append(
            ChatHistoryTurn(
                question=row["question"],
                answer="\n\n".join(b.text for b in artifact.blocks),
                scope_fingerprint=scope.fingerprint,
            )
        )
    return select_history(turns, scope.fingerprint)


async def save_feedback(owner, answer_id, body):
    async with transaction() as conn:
        answer, scope = await qa_read.owned_answer(owner, answer_id, conn=conn)
        qa_read.checked_artifact(answer, scope)
        feedback_id = uid("qaf")
        await execute(
            "INSERT INTO qa_feedback(feedback_id,answer_id,owner_id,rating,reason,comment,evaluation_consent) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE rating=%s,reason=%s,"
            "comment=%s,evaluation_consent=%s,updated_at=UTC_TIMESTAMP(6)",
            (
                feedback_id,
                answer_id,
                owner,
                body.rating,
                body.reason,
                body.comment,
                body.evaluation_consent,
                body.rating,
                body.reason,
                body.comment,
                body.evaluation_consent,
            ),
            conn=conn,
        )
        saved = await fetch_one(
            "SELECT feedback_id FROM qa_feedback WHERE answer_id=%s AND owner_id=%s",
            (answer_id, owner),
            conn=conn,
        )
    return saved


async def purge_document(owner, doc_id):
    """Erase derived QA text after the durable cleanup commits a source tombstone."""
    rows = await fetch_all(
        "SELECT session_id,revision,scope_json FROM qa_scope_revisions WHERE owner_id=%s ORDER BY session_id,revision",
        (owner,),
    )
    for row in rows:
        if not any(
            source.get("doc_id") == doc_id
            for source in load(row["scope_json"], {}).get("documents", [])
        ):
            continue
        args = (row["session_id"], row["revision"], owner)
        async with transaction() as conn:
            # Revocation prevents new tasks in this revision. Lock its existing
            # tasks in a stable order, then the session, then derived content.
            # This matches worker publication and lets a concurrent submission
            # into a newer revision finish without a message/session lock cycle.
            tasks = await fetch_all(
                "SELECT task_id FROM qa_messages WHERE session_id=%s AND scope_revision=%s AND owner_id=%s "
                "AND role='assistant' ORDER BY task_id",
                args,
                conn=conn,
            )
            for task in tasks:
                await execute(
                    "UPDATE quiz_tasks SET request_json=JSON_REMOVE(request_json,'$.question'),user_input='',result_json=NULL "
                    "WHERE task_id=%s AND user_id=%s",
                    (task["task_id"], owner),
                    conn=conn,
                )
            await qa_read.owned_session(owner, row["session_id"], conn=conn, lock=True)
            await execute(
                "UPDATE qa_feedback f JOIN qa_answers a ON a.answer_id=f.answer_id SET f.comment='',f.evaluation_consent=FALSE "
                "WHERE a.session_id=%s AND a.scope_revision=%s AND a.owner_id=%s",
                args,
                conn=conn,
            )
            await execute(
                "UPDATE qa_answers SET artifact_json=NULL WHERE session_id=%s AND scope_revision=%s AND owner_id=%s",
                args,
                conn=conn,
            )
            await execute(
                "UPDATE qa_messages SET content='',status='revoked' WHERE session_id=%s AND scope_revision=%s AND owner_id=%s",
                args,
                conn=conn,
            )
            await execute(
                "UPDATE qa_sessions SET title='资料已失效的会话' WHERE session_id=%s AND scope_revision=%s AND owner_id=%s",
                args,
                conn=conn,
            )
