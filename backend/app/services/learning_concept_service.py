"""Persistent concepts and server-verified question-to-concept associations."""

import json

from pydantic import ValidationError

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load, uid
from app.learning.contracts import QuestionConceptBinding
from app.learning.quiz_identity import canonical_quiz_question_version
from app.practice.contracts import PracticeArtifact
from app.rag.contracts import ArtifactQuestion, QuizArtifact, ResolvedScope, Usage
from app.rag.errors import SourceUnavailable
from app.rag.scope import evidence_in_scope
from app.services import learning_scope_service as scopes
from app.services import source_service

REVOKED_CONCEPT_TITLE = "资料已失效的概念"


async def owned_concept(owner_id, concept_id, *, conn=None, lock=False):
    if lock and conn is None:
        raise ValueError("A concept lock requires an existing transaction")
    row = await fetch_one(
        "SELECT * FROM learning_concepts WHERE concept_id=%s AND owner_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (concept_id, owner_id),
        conn=conn,
    )
    if row is None:
        raise not_found()
    return row


async def concept_view(row, *, conn=None):
    scope = await scopes.stored_scope(
        row["owner_id"], row["space_id"], row["scope_revision"], conn=conn
    )
    available = await scopes.scope_available(scope, conn=conn)
    return {
        "concept_id": row["concept_id"],
        "space_id": row["space_id"],
        "scope_revision": row["scope_revision"],
        "title": row["title"] if available else REVOKED_CONCEPT_TITLE,
        "revision": row["revision"],
        "created_at": iso(row["created_at"]),
        "source_status": "active" if available else "revoked",
    }


async def list_concepts(owner_id, space_id):
    async with transaction() as conn:
        await scopes.owned_space(owner_id, space_id, conn=conn)
        rows = await fetch_all(
            "SELECT * FROM learning_concepts WHERE space_id=%s AND owner_id=%s ORDER BY created_at,concept_id",
            (space_id, owner_id),
            conn=conn,
        )
        return {"items": [await concept_view(row, conn=conn) for row in rows]}


async def create_concept(actor, space_id, body):
    async with transaction() as conn:
        space = await scopes.owned_space(actor.owner_id, space_id, conn=conn, lock=True)
        scopes.require_active(space)
        revision = body.scope_revision or space["active_scope_revision"]
        await scopes.read_scope(actor.owner_id, space_id, revision, conn=conn)
        concept_id = uid("concept")
        await execute(
            "INSERT INTO learning_concepts(concept_id,owner_id,space_id,scope_revision,title) VALUES(%s,%s,%s,%s,%s)",
            (concept_id, actor.owner_id, space_id, revision, body.title),
            conn=conn,
        )
        return await concept_view(
            await owned_concept(actor.owner_id, concept_id, conn=conn), conn=conn
        )


async def update_concept(actor, concept_id, body):
    preview = await owned_concept(actor.owner_id, concept_id)
    async with transaction() as conn:
        space = await scopes.owned_space(
            actor.owner_id, preview["space_id"], conn=conn, lock=True
        )
        current = await owned_concept(actor.owner_id, concept_id, conn=conn)
        if current["revision"] != body.expected_revision:
            raise conflict("revision_conflict", "概念已更新，请刷新后重试")
        revision = body.scope_revision or space["active_scope_revision"]
        # A rename is explicit new text: its provenance may move to an
        # authorized scope without reading the previous, possibly revoked title.
        await scopes.read_scope(actor.owner_id, space["space_id"], revision, conn=conn)
        await owned_concept(actor.owner_id, concept_id, conn=conn, lock=True)
        await execute(
            "UPDATE learning_concepts SET title=%s,scope_revision=%s,revision=revision+1,updated_at=UTC_TIMESTAMP(6) "
            "WHERE concept_id=%s AND owner_id=%s",
            (body.title, revision, concept_id, actor.owner_id),
            conn=conn,
        )
        return await concept_view(
            await owned_concept(actor.owner_id, concept_id, conn=conn), conn=conn
        )


async def _quiz_origin(conn, owner_id, origin_id, space_id, scope_revision):
    quiz = await fetch_one(
        "SELECT * FROM quiz_sessions WHERE quiz_id=%s AND user_id=%s FOR UPDATE",
        (origin_id, owner_id),
        conn=conn,
    )
    if quiz is None:
        raise not_found()
    context = await fetch_one(
        "SELECT * FROM learning_quiz_contexts WHERE quiz_id=%s AND owner_id=%s",
        (origin_id, owner_id),
        conn=conn,
    )
    if context is None or (context["space_id"], context["scope_revision"]) != (
        space_id,
        scope_revision,
    ):
        raise not_found()
    try:
        actual_scope = ResolvedScope.model_validate(load(quiz["source_scope_json"]))
        recorded_scope = ResolvedScope.model_validate(
            load(context["source_scope_json"])
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise not_found() from exc
    if (
        actual_scope.fingerprint != recorded_scope.fingerprint
        or actual_scope.fingerprint != context["scope_fingerprint"]
    ):
        raise not_found()
    return quiz, actual_scope


async def _checked_quiz_questions(conn, owner_id, quiz, actual_scope):
    run = await fetch_one(
        "SELECT * FROM rag_runs WHERE run_id=%s AND owner_id=%s AND mode='production' "
        "AND namespace='production' AND status='completed'",
        (quiz["rag_run_id"], owner_id),
        conn=conn,
    )
    if run is None or not run["evidence_artifact_key"]:
        raise not_found()
    try:
        payload = json.loads(
            source_service.artifacts()
            .resolve_key(run["evidence_artifact_key"])
            .read_bytes()
        )
        if digest(dump(payload)) != run["evidence_hash"]:
            raise not_found()
        artifact = QuizArtifact.model_validate(
            {
                **payload,
                "usage": {
                    key: value
                    for key, value in payload.get("usage", {}).items()
                    if key in Usage.model_fields
                },
            }
        )
        manifest_scope = ResolvedScope.model_validate(
            load(run["manifest_json"])["resolved_scope"]
        )
        saved = [
            ArtifactQuestion.model_validate(
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"image_status", "image_url"}
                }
            )
            for item in load(quiz["questions_json"], [])
        ]
    except (
        OSError,
        SourceUnavailable,
        ValidationError,
        ValueError,
        TypeError,
        KeyError,
    ) as exc:
        raise not_found() from exc
    if (
        artifact.owner_id != owner_id
        or artifact.mode != "production"
        or artifact.run_id != run["run_id"]
        or not artifact.validation.passed
        or artifact.evidence_pack.resolved_scope.fingerprint != actual_scope.fingerprint
        or manifest_scope.fingerprint != actual_scope.fingerprint
        or any(
            not evidence_in_scope(item, actual_scope)
            for item in artifact.evidence_pack.evidence
        )
        or saved != artifact.questions
        or len({question.id for question in saved}) != len(saved)
    ):
        raise not_found()
    return {
        question.id: (
            canonical_quiz_question_version(question, artifact.evidence_pack),
            question.coverage_target_id,
        )
        for question in artifact.questions
    }


async def _practice_origin(
    conn, owner_id, origin_id, space_id, scope_revision, *, metadata_only=False
):
    from app.services.practice_dependencies import METADATA_SQL

    columns = (
        "practice_id,owner_id,space_id,scope_revision,status,error_code,"
        "source_scope_json,artifact_hash,generation_task_id," + METADATA_SQL
        if metadata_only
        else "*"
    )
    session = await fetch_one(
        f"SELECT {columns} FROM practice_sessions WHERE practice_id=%s AND owner_id=%s FOR UPDATE",
        (origin_id, owner_id),
        conn=conn,
    )
    if session is None or (session["space_id"], session["scope_revision"]) != (
        space_id,
        scope_revision,
    ):
        raise not_found()
    try:
        actual_scope = ResolvedScope.model_validate(load(session["source_scope_json"]))
    except (ValidationError, ValueError, TypeError) as exc:
        raise not_found() from exc
    return session, actual_scope


async def _checked_practice_questions(conn, owner_id, session, actual_scope):
    try:
        payload = load(session["artifact_json"])
        if not payload or digest(dump(payload)) != session["artifact_hash"]:
            raise not_found()
        artifact = PracticeArtifact.model_validate(payload)
    except (ValidationError, ValueError, TypeError) as exc:
        raise not_found() from exc
    if (
        artifact.owner_id != owner_id
        or artifact.mode != "production"
        or artifact.space_id != session["space_id"]
        or artifact.scope_revision != session["scope_revision"]
        or artifact.scope_fingerprint != actual_scope.fingerprint
        or artifact.evidence_pack.resolved_scope.fingerprint != actual_scope.fingerprint
    ):
        raise not_found()
    rows = await fetch_all(
        "SELECT question_id,question_version,rubric_version,rubric_hash FROM practice_questions "
        "WHERE practice_id=%s AND owner_id=%s ORDER BY question_id",
        (session["practice_id"], owner_id),
        conn=conn,
    )
    saved = {
        row["question_id"]: (
            row["question_version"],
            row["rubric_version"],
            row["rubric_hash"],
        )
        for row in rows
    }
    expected = {
        question.id: (
            artifact.question_versions[question.id],
            question.rubric.version,
            artifact.rubric_hashes[question.id],
        )
        for question in artifact.questions
    }
    if saved != expected:
        raise not_found()
    return {
        question_id: (version, None)
        for question_id, version in artifact.question_versions.items()
    }


async def bind_questions(
    conn,
    owner_id: int,
    *,
    origin_kind: str,
    origin_id: str,
    space_id: str,
    scope_revision: int,
    question_concepts: list[QuestionConceptBinding],
) -> None:
    if conn is None:
        raise ValueError("Question binding requires an existing transaction")
    bindings = [
        QuestionConceptBinding.model_validate(item) for item in question_concepts
    ]
    if (
        not bindings
        or len(bindings) > 10
        or len({item.question_id for item in bindings}) != len(bindings)
    ):
        raise AppError(
            422, "invalid_question_bindings", "题目关联必须包含互不重复的有效题目"
        )
    if origin_kind not in {"quiz", "practice"}:
        raise not_found()
    space = await scopes.owned_space(owner_id, space_id, conn=conn, lock=True)
    scopes.require_active(space)
    if origin_kind == "quiz":
        origin, actual_scope = await _quiz_origin(
            conn, owner_id, origin_id, space_id, scope_revision
        )
    else:
        origin, actual_scope = await _practice_origin(
            conn, owner_id, origin_id, space_id, scope_revision
        )
    space_scope = await scopes.stored_scope(
        owner_id, space_id, scope_revision, conn=conn
    )
    if not scopes.scope_covers(space_scope, actual_scope):
        raise not_found()
    concept_ids = sorted(
        {concept_id for item in bindings for concept_id in item.concept_ids}
    )
    concepts = []
    for concept_id in concept_ids:
        row = await owned_concept(owner_id, concept_id, conn=conn)
        if row["space_id"] != space_id:
            raise not_found()
        concepts.append(row)
    # Collect complete immutable snapshots before any source lock, including
    # uncited activity documents and historical concept metadata dependencies.
    required_scopes = [space_scope, actual_scope]
    for revision in sorted({row["scope_revision"] for row in concepts}):
        required_scopes.append(
            await scopes.stored_scope(owner_id, space_id, revision, conn=conn)
        )
    await scopes.require_sources(required_scopes, conn=conn)
    questions = (
        await _checked_quiz_questions(conn, owner_id, origin, actual_scope)
        if origin_kind == "quiz"
        else await _checked_practice_questions(conn, owner_id, origin, actual_scope)
    )
    for preview in concepts:
        current = await owned_concept(
            owner_id, preview["concept_id"], conn=conn, lock=True
        )
        # A pre-existing RR snapshot may predate the space lock. Abort instead
        # of authorizing newly discovered provenance after locking concepts.
        if (current["space_id"], current["scope_revision"]) != (
            preview["space_id"],
            preview["scope_revision"],
        ):
            raise conflict("concept_scope_conflict", "概念来源范围已更新，请刷新后重试")
    pending = []
    for binding in sorted(bindings, key=lambda item: item.question_id):
        question = questions.get(binding.question_id)
        if question is None:
            raise not_found()
        version, coverage_target = question
        if binding.question_version != version:
            raise conflict("question_version_conflict", "题目版本与已保存工件不一致")
        existing = await fetch_all(
            "SELECT concept_id,question_version,space_id,scope_revision,coverage_target_id FROM question_concepts "
            "WHERE owner_id=%s AND origin_kind=%s AND origin_id=%s AND question_id=%s "
            "ORDER BY concept_id FOR UPDATE",
            (owner_id, origin_kind, origin_id, binding.question_id),
            conn=conn,
        )
        expected = {
            (concept_id, version, space_id, scope_revision, coverage_target)
            for concept_id in binding.concept_ids
        }
        actual = {
            (
                row["concept_id"],
                row["question_version"],
                row["space_id"],
                row["scope_revision"],
                row["coverage_target_id"],
            )
            for row in existing
        }
        if existing:
            if actual != expected:
                raise conflict(
                    "question_binding_conflict", "此题已经关联到不同的概念或范围"
                )
        else:
            pending.extend(
                (binding.question_id, concept_id, version, coverage_target)
                for concept_id in sorted(binding.concept_ids)
            )
    for question_id, concept_id, version, coverage_target in pending:
        await execute(
            "INSERT INTO question_concepts(owner_id,origin_kind,origin_id,question_id,question_version,concept_id,space_id,scope_revision,coverage_target_id) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                owner_id,
                origin_kind,
                origin_id,
                question_id,
                version,
                concept_id,
                space_id,
                scope_revision,
                coverage_target,
            ),
            conn=conn,
        )
