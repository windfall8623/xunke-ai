"""QA execution in the existing single owner, with fenced atomic publication."""

from app.core.db import execute, fetch_one, transaction
from app.core.errors import conflict, not_found
from app.core.values import digest, dump, load, now
from app.qa.contracts import ChatAnswerArtifact
from app.rag.contracts import (
    BudgetLimits,
    ExecutionContext,
    PipelineConfig,
    ResolvedScope,
)
from app.rag.errors import ScopeRevoked
from app.rag.scope import require_execution_scope
from app.services import job_service, qa_read, qa_service


async def run_qa(job, actor, engine, *, usage_loader):
    if job["mode"] != "production":
        raise ScopeRevoked("QA sessions are a production-only artifact")
    request = job["request"]
    async with transaction() as conn:
        await job_service.locked_job(job, conn)
        session = await qa_read.owned_session(
            actor.owner_id, request["session_id"], conn=conn, lock=True
        )
        if (
            session["active_task_id"] != job["task_id"]
            or session["scope_revision"] != request["scope_revision"]
        ):
            raise conflict("qa_session_changed", "会话范围或活动任务已变化")
        scope = await qa_read.revision_scope(
            actor.owner_id, session["session_id"], request["scope_revision"], conn=conn
        )
        if scope != ResolvedScope.model_validate(job["scope"]):
            raise ScopeRevoked("QA job differs from its pinned source revision")
        await qa_read.require_source(scope, conn=conn)
        question = await fetch_one(
            "SELECT content,sequence FROM qa_messages WHERE message_id=%s AND session_id=%s AND owner_id=%s "
            "AND task_id=%s AND role='user' AND scope_revision=%s",
            (
                request["user_message_id"],
                session["session_id"],
                actor.owner_id,
                job["task_id"],
                request["scope_revision"],
            ),
            conn=conn,
        )
        if not question or question["content"] != request["question"]:
            raise not_found()
        assistant = await fetch_one(
            "SELECT message_id FROM qa_messages WHERE message_id=%s AND task_id=%s AND role='assistant' AND owner_id=%s",
            (request["assistant_message_id"], job["task_id"], actor.owner_id),
            conn=conn,
        )
        if not assistant:
            raise not_found()
        history = await qa_service.history_for_job(
            actor.owner_id,
            session["session_id"],
            request["scope_revision"],
            scope,
            question["sequence"],
            conn=conn,
        )
        await execute(
            "UPDATE qa_messages SET status='running',started_at=COALESCE(started_at,UTC_TIMESTAMP(6)) "
            "WHERE message_id=%s",
            (assistant["message_id"],),
            conn=conn,
        )
    context = ExecutionContext(
        mode="production",
        run_id="rag_" + digest(job["task_id"])[:32],
        storage_namespace=scope.namespace,
        budget=BudgetLimits(
            deadline_seconds=min(
                1800, max(0.001, (job["deadline_at"] - now()).total_seconds())
            )
        ),
    )
    require_execution_scope(actor, context, scope)
    config = PipelineConfig.model_validate(request["pipeline_config"])

    async def progress(stage):
        await job_service.heartbeat(job, stage)

    await progress("retrieving")
    artifact = ChatAnswerArtifact.model_validate(
        await engine.answer(
            question["content"],
            history,
            actor,
            context,
            scope,
            config,
            progress=progress,
        )
    )
    if (
        artifact.run_id != context.run_id
        or artifact.scope_fingerprint != scope.fingerprint
    ):
        raise ScopeRevoked("QA answer identity differs from its execution context")
    for item in artifact.evidence:
        engine.verify_evidence(item, scope)
    payload = artifact.model_dump(mode="json")
    payload["usage"] = await usage_loader(job, payload["usage"])
    answer_id = "qaa_" + digest(job["task_id"])[:32]

    async def publish(current, result, conn):
        pinned = await qa_read.owned_session(
            actor.owner_id, request["session_id"], conn=conn, lock=True
        )
        if (
            pinned["active_task_id"] != current["task_id"]
            or pinned["scope_revision"] != request["scope_revision"]
        ):
            raise conflict("qa_session_changed", "会话范围或活动任务已变化")
        await qa_read.require_source(scope, conn=conn)
        await execute(
            "INSERT INTO qa_answers(answer_id,session_id,owner_id,message_id,task_id,scope_revision,artifact_json,artifact_hash,usage_json) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                answer_id,
                request["session_id"],
                actor.owner_id,
                request["assistant_message_id"],
                current["task_id"],
                request["scope_revision"],
                dump(payload),
                digest(dump(payload)),
                dump(payload["usage"]),
            ),
            conn=conn,
        )
        # MySQL binary JSON can normalize floating-point telemetry by one ULP.
        # Seal the actual stored representation before this transaction publishes
        # anything; subsequent reads still reject all unauthorized modifications.
        stored = await fetch_one(
            "SELECT artifact_json FROM qa_answers WHERE answer_id=%s",
            (answer_id,),
            conn=conn,
        )
        await execute(
            "UPDATE qa_answers SET artifact_hash=%s WHERE answer_id=%s",
            (digest(dump(load(stored["artifact_json"]))), answer_id),
            conn=conn,
        )
        # Depend on the whole selected scope, including material influencing a
        # refusal or an unquoted inference. Revocation cannot miss these inputs.
        for source in scope.documents:
            await execute(
                "INSERT INTO qa_answer_sources(answer_id,owner_id,doc_id,document_version_id,authorization_revision) VALUES(%s,%s,%s,%s,%s)",
                (
                    answer_id,
                    actor.owner_id,
                    source.doc_id,
                    source.document_version_id,
                    source.authorization_revision,
                ),
                conn=conn,
            )
        await execute(
            "UPDATE qa_messages SET content=%s,status='completed',finished_at=UTC_TIMESTAMP(6),error_code=NULL "
            "WHERE message_id=%s",
            (
                "\n\n".join(b.text for b in artifact.blocks),
                request["assistant_message_id"],
            ),
            conn=conn,
        )
        await execute(
            "UPDATE qa_sessions SET active_task_id=NULL,updated_at=UTC_TIMESTAMP(6) WHERE session_id=%s",
            (request["session_id"],),
            conn=conn,
        )

    await job_service.complete_job(job, {"answer_id": answer_id}, publisher=publish)
