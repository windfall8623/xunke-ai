"""Fixed-source practice generation and shared review occurrence binding."""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import Field, ValidationError, model_validator
from pymysql import OperationalError

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, load, uid
from app.learning.contracts import LearningId
from app.models.practice import (
    PracticeTaskView,
    PracticeView,
    ReviewPracticeBody,
    public_question,
)
from app.models.sources import PublicResolvedScope
from app.practice.contracts import PracticeArtifact, PracticePayload, PracticeSpec
from app.practice.validation import validate_practice_payload
from app.prompts.practice_prompt import PROMPT_HASH, PROMPT_VERSION
from app.rag.contracts import (
    ActorContext,
    Contract,
    Hash,
    Identity,
    PipelineConfig,
    ResolvedScope,
)
from app.rag.errors import RagError, SourceUnavailable
from app.services import (
    job_service,
    learning_concept_service,
    review_service,
    source_service,
)
from app.services import learning_scope_service as scopes

PositiveRevision = Annotated[int, Field(ge=1)]
_SAFE_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z")
_PUBLIC_STAGES = {
    "queued",
    "pending",
    "starting",
    "retrieving",
    "generating",
    "grading",
    "validating",
    "publishing",
    "completed",
    "failed",
    "cancelled",
    "reconciled",
}


class ReviewPracticeOrigin(Contract):
    kind: Literal["review"] = "review"
    review_task_ids: list[LearningId] = Field(min_length=1, max_length=3)
    expected_revisions: dict[LearningId, PositiveRevision]

    @model_validator(mode="after")
    def complete_occurrences(self):
        if len(self.review_task_ids) != len(set(self.review_task_ids)) or set(
            self.review_task_ids
        ) != set(self.expected_revisions):
            raise ValueError("Every review occurrence requires its frozen revision")
        return self


class PracticeGenerationRequest(Contract):
    """Private, server-owned envelope; the HTTP body remains PracticeSpec only."""

    practice_id: LearningId
    generation_request_id: LearningId
    spec: PracticeSpec
    scope_fingerprint: Hash
    pipeline_id: Identity
    pipeline_config: PipelineConfig
    prompt_hash: Hash
    concept_scope_revisions: dict[LearningId, PositiveRevision]
    space_title_scope_revision: PositiveRevision
    origin: ReviewPracticeOrigin | None = None

    @model_validator(mode="after")
    def complete_metadata_provenance(self):
        if set(self.concept_scope_revisions) != set(self.spec.concept_ids):
            raise ValueError("Saved concept provenance must exactly cover the request")
        if self.generation_request_id != self.practice_id:
            raise ValueError("The logical generation identity belongs to one practice")
        return self


def generation_request(raw) -> PracticeGenerationRequest:
    try:
        return PracticeGenerationRequest.model_validate(
            load(raw) if isinstance(raw, (str, bytes)) else raw
        )
    except (ValidationError, ValueError, TypeError) as exc:
        raise not_found() from exc


def _generation_changed():
    return conflict("practice_generation_changed", "练习生成任务已变化")


def _validate_key(key):
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise AppError(422, "idempotency_required", "需要有效 Idempotency-Key")


def require_practice_generation_types(question_types):
    from app.practice.grading_config import require_generation_types

    require_generation_types(question_types)


def review_practice_request_hash(body: ReviewPracticeBody) -> str:
    request = body.model_dump(mode="json")
    request["review_task_ids"] = sorted(request["review_task_ids"])
    return digest(dump({"entrypoint": "practice.review", "request": request}))


def generation_request_hash(request: PracticeGenerationRequest) -> str:
    if request.origin is not None:
        return review_practice_request_hash(
            ReviewPracticeBody(
                review_task_ids=request.origin.review_task_ids,
                expected_revisions=request.origin.expected_revisions,
                question_types=request.spec.question_types,
                question_count=request.spec.question_count,
                difficulty=request.spec.difficulty,
            )
        )
    return digest(dump(request.spec.model_dump(mode="json")))


def _pipeline_selection():
    # Select only from the existing server registry; no user-supplied provider,
    # price, output bound or pipeline options cross this service boundary.
    from app.services.evaluation_service import pipeline_config

    pipeline_id = get_settings().rag_pipeline_id
    if pipeline_id == "legacy-summary-b0":
        raise AppError(422, "unsupported_pipeline", "练习需要固定资料检索方案")
    raw = pipeline_config(pipeline_id).model_dump(mode="json")
    raw.update(
        prompt_version=PROMPT_VERSION,
        max_retrieval_rounds=1,
        max_subqueries=1,
        max_generation_attempts=2,
        max_llm_calls=5,
        require_semantic_validation=True,
    )
    return pipeline_id, PipelineConfig.model_validate(raw)


async def owned_practice(owner_id, practice_id, *, conn=None, lock=False) -> dict:
    """Ownership lookup only. Derived text still requires authorize_practice."""
    if lock and conn is None:
        raise ValueError("A practice lock requires an existing transaction")
    row = await fetch_one(
        "SELECT * FROM practice_sessions WHERE practice_id=%s AND owner_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (practice_id, owner_id),
        conn=conn,
    )
    if row is None:
        raise not_found()
    return row


async def lock_practice_space(conn, owner_id, space_id) -> None:
    if conn is None:
        raise ValueError("A space lock requires an existing transaction")
    await scopes.owned_space(owner_id, space_id, conn=conn, lock=True)


async def owned_practice_task(owner_id, task_id, *, conn=None, lock=False):
    if lock and conn is None:
        raise ValueError("A task lock requires an existing transaction")
    row = await fetch_one(
        "SELECT * FROM quiz_tasks WHERE task_id=%s AND user_id=%s AND mode='production' "
        "AND ((kind='practice_generate' AND operation='practice.generate') "
        "OR (kind='practice_grade' AND operation='practice.grade'))"
        + (" FOR UPDATE" if lock else ""),
        (task_id, owner_id),
        conn=conn,
    )
    if row is None:
        raise not_found()
    return job_service.decode(row)


async def _concept_previews(owner_id, spec, conn):
    previews = []
    for concept_id in sorted(spec.concept_ids):
        concept = await learning_concept_service.owned_concept(
            owner_id, concept_id, conn=conn
        )
        if concept["space_id"] != spec.space_id:
            raise not_found()
        previews.append(concept)
    return previews


async def _authorize_dependencies(
    conn, owner_id, space, request, activity_scope, previews
):
    # The immutable request retains the metadata scopes used at creation. The
    # current metadata scopes are also needed by the accepted binding helper.
    revisions = {
        request.spec.scope_revision,
        request.space_title_scope_revision,
        space["title_scope_revision"],
        *request.concept_scope_revisions.values(),
        *(row["scope_revision"] for row in previews),
    }
    required = [activity_scope]
    for revision in sorted(revisions):
        required.append(
            await scopes.stored_scope(owner_id, space["space_id"], revision, conn=conn)
        )
    await scopes.require_sources(required, conn=conn)
    for preview in previews:
        current = await learning_concept_service.owned_concept(
            owner_id, preview["concept_id"], conn=conn, lock=True
        )
        # A caller may have established an RR snapshot before acquiring the
        # space lock. Never discover and lock new sources after concept locks.
        if (current["space_id"], current["scope_revision"], current["revision"]) != (
            preview["space_id"],
            preview["scope_revision"],
            preview["revision"],
        ):
            raise conflict("concept_scope_conflict", "概念来源范围已更新，请刷新后重试")


def _row_request_scope(row):
    request = generation_request(row["generation_request_json"])
    try:
        scope = ResolvedScope.model_validate(load(row["source_scope_json"]))
    except (ValidationError, ValueError, TypeError) as exc:
        raise not_found() from exc
    if (
        request.practice_id != row["practice_id"]
        or request.spec.space_id != row["space_id"]
        or request.spec.scope_revision != row["scope_revision"]
        or scope.owner_id != row["owner_id"]
        or scope.namespace != "production"
        or not scope.documents
        or request.scope_fingerprint != scope.fingerprint
    ):
        raise not_found()
    return request, scope


def require_generation_job(job, row, request, scope):
    """Validate immutable envelopes in addition to job_service's lease fence."""
    try:
        saved = generation_request(job["request"])
        job_scope = ResolvedScope.model_validate(job["scope"])
    except (KeyError, ValidationError, ValueError, TypeError) as exc:
        raise not_found() from exc
    if (
        job["user_id"] != row["owner_id"]
        or job["mode"] != "production"
        or job["kind"] != "practice_generate"
        or job["operation"] != "practice.generate"
        or saved != request
        or job_scope != scope
        or job["request_hash"] != generation_request_hash(request)
    ):
        raise not_found()


async def authorize_practice(
    conn, owner_id, practice_id, *, job=None, generating=False, active=False
):
    """Lock space → practice → all original sources → sorted concepts.

    The caller must acquire the task first if a job is involved. This helper is
    also available to the later answer service without making a second scope gate.
    """
    if conn is None:
        raise ValueError("Practice authorization requires an existing transaction")
    preview = None
    if job is not None:
        # An enqueue loser may have an RR snapshot from before the winner's
        # commit. The current, locked task supplies the immutable space locator;
        # a snapshot-only practice preview would incorrectly hide that winner.
        hint = generation_request(job["request"])
        if hint.practice_id != practice_id:
            raise not_found()
        space_id = hint.spec.space_id
    else:
        preview = await owned_practice(owner_id, practice_id, conn=conn)
        space_id = preview["space_id"]
        hint = generation_request(preview["generation_request_json"])
        if hint.origin is not None:
            # Shared review authorization locks its task before the activity.
            job = await owned_practice_task(
                owner_id, preview["generation_task_id"], conn=conn, lock=True
            )
    space = await scopes.owned_space(owner_id, space_id, conn=conn, lock=True)
    row = await owned_practice(owner_id, practice_id, conn=conn, lock=True)
    if row["space_id"] != space_id or (
        preview is not None and row["scope_revision"] != preview["scope_revision"]
    ):
        raise _generation_changed()
    if active:
        scopes.require_active(space)
    request, scope = _row_request_scope(row)
    fixed = await scopes.stored_scope(
        owner_id, row["space_id"], row["scope_revision"], conn=conn
    )
    if fixed != scope:
        raise not_found()
    if job is not None:
        require_generation_job(job, row, request, scope)
        if generating and row["generation_task_id"] != job["task_id"]:
            raise _generation_changed()
    if generating and (
        row["status"] != "generating"
        or row["artifact_json"] is not None
        or row["artifact_hash"] is not None
    ):
        raise _generation_changed()
    if request.origin is not None:
        batch = await review_service.authorize_review_binding(
            conn,
            owner_id,
            review_task_ids=request.origin.review_task_ids,
            expected_revisions=request.origin.expected_revisions,
            task_id=job["task_id"],
            origin_kind="practice",
            origin_id=practice_id,
            scope=scope,
            request_hash=generation_request_hash(request),
            provenance_revisions=(
                request.space_title_scope_revision,
                *request.concept_scope_revisions.values(),
            ),
            require_active=active,
        )
        if set(batch.concept_ids) != set(request.spec.concept_ids):
            raise conflict("review_binding_conflict", "复习概念与已保存的练习不一致")
    else:
        previews = await _concept_previews(owner_id, request.spec, conn)
        await _authorize_dependencies(conn, owner_id, space, request, scope, previews)
    return row, request, scope


async def _create_generation(actor, body, key, request_hash):
    async with transaction() as conn:
        # A nonlocking first lookup avoids an empty unique-key gap lock. Existing
        # replay takes the task lock before the space/activity locks.
        replay = await job_service.existing_job(
            actor.owner_id, "practice_generate", key, request_hash, conn=conn
        )
        if replay:
            replay = await owned_practice_task(
                actor.owner_id, replay["task_id"], conn=conn, lock=True
            )
            if replay["request_hash"] != request_hash:
                raise conflict("idempotency_conflict", "相同操作标识已用于不同请求")
            pinned = generation_request(replay["request"])
            await authorize_practice(
                conn, actor.owner_id, pinned.practice_id, job=replay
            )
            return replay["task_id"]
        space = await scopes.owned_space(
            actor.owner_id, body.space_id, conn=conn, lock=True
        )
        scopes.require_active(space)
        scope = await scopes.stored_scope(
            actor.owner_id, body.space_id, body.scope_revision, conn=conn
        )
        previews = await _concept_previews(actor.owner_id, body, conn)
        pipeline_id, config = _pipeline_selection()
        practice_id = uid("practice")
        request = PracticeGenerationRequest(
            practice_id=practice_id,
            generation_request_id=practice_id,
            spec=body,
            scope_fingerprint=scope.fingerprint,
            pipeline_id=pipeline_id,
            pipeline_config=config,
            prompt_hash=PROMPT_HASH,
            concept_scope_revisions={
                row["concept_id"]: row["scope_revision"] for row in previews
            },
            space_title_scope_revision=space["title_scope_revision"],
        )
        job = await job_service.enqueue_job(
            actor.owner_id,
            "practice_generate",
            request.model_dump(mode="json"),
            key,
            scope=scope.model_dump(mode="json"),
            conn=conn,
            request_hash=request_hash,
        )
        winner = generation_request(job["request"])
        if winner.practice_id != practice_id:
            # A concurrent creator won the unique key. Use its persisted
            # envelope; never insert a session for this losing preallocated ID.
            job = await owned_practice_task(
                actor.owner_id, job["task_id"], conn=conn, lock=True
            )
            await authorize_practice(conn, actor.owner_id, winner.practice_id, job=job)
            return job["task_id"]
        await execute(
            "INSERT INTO practice_sessions(practice_id,owner_id,space_id,scope_revision,generation_task_id,"
            "generation_request_json,source_scope_json,status) VALUES(%s,%s,%s,%s,%s,%s,%s,'generating')",
            (
                practice_id,
                actor.owner_id,
                body.space_id,
                body.scope_revision,
                job["task_id"],
                dump(request),
                dump(scope),
            ),
            conn=conn,
        )
        # The new activity root exists before any source/concept locks. Failure
        # rolls back both it and the queued task; no pending orphan is visible.
        await _authorize_dependencies(
            conn, actor.owner_id, space, request, scope, previews
        )
        return job["task_id"]


async def create_practice_job(
    actor: ActorContext, body: PracticeSpec, key: str
) -> PracticeTaskView:
    _validate_key(key)
    body = PracticeSpec.model_validate(body.model_dump(mode="json"))
    require_practice_generation_types(body.question_types)
    request_hash = digest(dump(body.model_dump(mode="json")))
    for attempt in range(3):
        try:
            task_id = await _create_generation(actor, body, key, request_hash)
            break
        except OperationalError as exc:
            # No provider I/O occurs in this transaction. A bounded replay is
            # safe when a concurrent unique-key winner meets owner lock ordering.
            if not exc.args or exc.args[0] not in {1205, 1213} or attempt == 2:
                raise
    return await get_practice_task(actor.owner_id, task_id)


async def _create_review_generation(actor, body, key, request_hash):
    # Replay is resolved before consulting current metadata or scope revision.
    async with transaction() as conn:
        replay = await job_service.existing_job(
            actor.owner_id, "practice_generate", key, request_hash, conn=conn
        )
        if replay:
            replay = await owned_practice_task(
                actor.owner_id, replay["task_id"], conn=conn, lock=True
            )
            request = generation_request(replay["request"])
            await authorize_practice(
                conn, actor.owner_id, request.practice_id, job=replay
            )
            return replay["task_id"]

    batch = await review_service.preview_review_batch(
        actor.owner_id, body.review_task_ids
    )
    spec = PracticeSpec(
        space_id=batch.space["space_id"],
        scope_revision=batch.reviews[0]["scope_revision"],
        objectives=[row["title"] for row in batch.concepts],
        concept_ids=batch.concept_ids,
        question_types=body.question_types,
        question_count=body.question_count,
        difficulty=body.difficulty,
    )
    pipeline_id, config = _pipeline_selection()
    practice_id = uid("practice")
    request = PracticeGenerationRequest(
        practice_id=practice_id,
        generation_request_id=practice_id,
        spec=spec,
        scope_fingerprint=batch.scope.fingerprint,
        pipeline_id=pipeline_id,
        pipeline_config=config,
        prompt_hash=PROMPT_HASH,
        concept_scope_revisions={
            row["concept_id"]: row["scope_revision"] for row in batch.concepts
        },
        space_title_scope_revision=batch.space["title_scope_revision"],
        origin=ReviewPracticeOrigin(
            review_task_ids=sorted(body.review_task_ids),
            expected_revisions=body.expected_revisions,
        ),
    )
    async with transaction() as conn:
        task = await job_service.enqueue_job(
            actor.owner_id,
            "practice_generate",
            request.model_dump(mode="json"),
            key,
            scope=batch.scope.model_dump(mode="json"),
            conn=conn,
            request_hash=request_hash,
        )
        task = await owned_practice_task(
            actor.owner_id, task["task_id"], conn=conn, lock=True
        )
        winner = generation_request(task["request"])
        if winner.practice_id != practice_id:
            await authorize_practice(conn, actor.owner_id, winner.practice_id, job=task)
            return task["task_id"]
        await lock_practice_space(conn, actor.owner_id, spec.space_id)
        await execute(
            "INSERT INTO practice_sessions(practice_id,owner_id,space_id,scope_revision,generation_task_id,"
            "generation_request_json,source_scope_json,status) VALUES(%s,%s,%s,%s,%s,%s,%s,'generating')",
            (
                practice_id,
                actor.owner_id,
                spec.space_id,
                spec.scope_revision,
                task["task_id"],
                dump(request),
                dump(batch.scope),
            ),
            conn=conn,
        )
        claimed = await review_service.claim_review_occurrences(
            conn,
            actor.owner_id,
            review_task_ids=body.review_task_ids,
            expected_revisions=body.expected_revisions,
            task_id=task["task_id"],
            origin_kind="practice",
            origin_id=practice_id,
            key=key,
            request_hash=request_hash,
            scope=batch.scope,
            provenance_revisions=(
                request.space_title_scope_revision,
                *request.concept_scope_revisions.values(),
            ),
        )
        if [
            (row["concept_id"], row["title"], row["scope_revision"], row["revision"])
            for row in claimed.concepts
        ] != [
            (row["concept_id"], row["title"], row["scope_revision"], row["revision"])
            for row in batch.concepts
        ]:
            raise conflict("concept_scope_conflict", "概念已更新，请刷新后重试")
        return task["task_id"]


async def create_review_practice_job(
    actor: ActorContext, body: ReviewPracticeBody, key: str
) -> PracticeTaskView:
    _validate_key(key)
    body = ReviewPracticeBody.model_validate(body.model_dump(mode="json"))
    require_practice_generation_types(body.question_types)
    request_hash = review_practice_request_hash(body)
    for attempt in range(3):
        try:
            task_id = await _create_review_generation(actor, body, key, request_hash)
            break
        except OperationalError as exc:
            if not exc.args or exc.args[0] not in {1205, 1213} or attempt == 2:
                raise
    return await get_practice_task(actor.owner_id, task_id)


def _checked_payload(row, request, scope, raw) -> PracticeArtifact:
    try:
        artifact = PracticeArtifact.model_validate(raw)
        payload = PracticePayload(
            title=artifact.title, summary=artifact.summary, questions=artifact.questions
        )
        errors = validate_practice_payload(
            payload, request.spec, artifact.evidence_pack
        )
    except (ValidationError, ValueError, TypeError, RagError) as exc:
        raise not_found() from exc
    if (
        artifact.owner_id != row["owner_id"]
        or artifact.mode != "production"
        or artifact.space_id != row["space_id"]
        or artifact.scope_revision != row["scope_revision"]
        or artifact.scope_fingerprint != scope.fingerprint
        or artifact.evidence_pack.resolved_scope != scope
        or artifact.pipeline_config_hash != request.pipeline_config.pipeline_config_hash
        or artifact.run_id != "rag_" + digest(row["generation_task_id"])[:32]
        or artifact.prompt_version != request.pipeline_config.prompt_version
        or artifact.prompt_hash != request.prompt_hash
        or errors
    ):
        raise not_found()
    return artifact


async def checked_practice_artifact(
    conn, row, request=None, scope=None
) -> PracticeArtifact:
    """Read exact persisted JSON and all immutable question/rubric indexes."""
    if request is None or scope is None:
        request, scope = _row_request_scope(row)
    raw = load(row["artifact_json"])
    if not raw or digest(dump(raw)) != row["artifact_hash"]:
        raise not_found()
    artifact = _checked_payload(row, request, scope, raw)
    saved = await fetch_all(
        "SELECT question_id,question_version,rubric_version,rubric_hash FROM practice_questions "
        "WHERE practice_id=%s AND owner_id=%s ORDER BY question_id FOR SHARE",
        (row["practice_id"], row["owner_id"]),
        conn=conn,
    )
    actual = {
        q["question_id"]: (q["question_version"], q["rubric_version"], q["rubric_hash"])
        for q in saved
    }
    expected = {
        q.id: (
            artifact.question_versions[q.id],
            q.rubric.version,
            artifact.rubric_hashes[q.id],
        )
        for q in artifact.questions
    }
    if actual != expected:
        raise not_found()
    return artifact


async def save_published_practice(conn, row, artifact) -> None:
    """Write → read/validate persisted JSON → hash/index, in the caller's tx.

    The caller holds task/space/practice locks and binds concepts in this same
    transaction. artifact_id is the generation identity; artifact_hash seals the
    exact stored payload, including MySQL's normalized floating telemetry.
    """
    if conn is None:
        raise ValueError("Practice publication requires an existing transaction")
    if (
        row["status"] != "generating"
        or row["artifact_json"] is not None
        or row["artifact_hash"] is not None
    ):
        raise _generation_changed()
    request, scope = _row_request_scope(row)
    artifact = _checked_payload(row, request, scope, artifact.model_dump(mode="json"))
    changed = await execute(
        "UPDATE practice_sessions SET artifact_json=%s WHERE practice_id=%s AND owner_id=%s "
        "AND generation_task_id=%s AND revision=%s AND status='generating' "
        "AND artifact_json IS NULL AND artifact_hash IS NULL",
        (
            dump(artifact),
            row["practice_id"],
            row["owner_id"],
            row["generation_task_id"],
            row["revision"],
        ),
        conn=conn,
    )
    if changed != 1:
        raise _generation_changed()
    stored = await owned_practice(
        row["owner_id"], row["practice_id"], conn=conn, lock=True
    )
    payload = load(stored["artifact_json"])
    persisted = _checked_payload(stored, request, scope, payload)
    if (
        persisted.artifact_id != artifact.artifact_id
        or persisted.question_versions != artifact.question_versions
        or persisted.rubric_hashes != artifact.rubric_hashes
        or persisted.questions != artifact.questions
    ):
        raise not_found()
    for question in persisted.questions:
        await execute(
            "INSERT INTO practice_questions(practice_id,question_id,owner_id,question_version,rubric_version,rubric_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s)",
            (
                row["practice_id"],
                question.id,
                row["owner_id"],
                persisted.question_versions[question.id],
                question.rubric.version,
                persisted.rubric_hashes[question.id],
            ),
            conn=conn,
        )
    changed = await execute(
        "UPDATE practice_sessions SET artifact_hash=%s,help_usage_json=%s,"
        "status='ready',revision=revision+1,error_code=NULL "
        "WHERE practice_id=%s AND owner_id=%s AND generation_task_id=%s AND revision=%s "
        "AND status='generating' AND artifact_json IS NOT NULL AND artifact_hash IS NULL",
        (
            digest(dump(payload)),
            dump({question.id: "none" for question in persisted.questions}),
            row["practice_id"],
            row["owner_id"],
            row["generation_task_id"],
            row["revision"],
        ),
        conn=conn,
    )
    if changed != 1:
        raise _generation_changed()


async def _generation_view(conn, row, request, scope) -> PracticeView:
    from app.services.practice_answer_service import read_practice_progress

    artifact = None
    progress = {}
    if row["artifact_json"] is not None:
        if row["status"] not in {"ready", "completed"}:
            raise not_found()
        artifact = await checked_practice_artifact(conn, row, request, scope)
        progress = await read_practice_progress(conn, row, artifact)
    elif (
        row["status"] in {"ready", "completed"}
        or row["artifact_hash"] is not None
        or row["completion_json"] is not None
        or row["completed_at"] is not None
    ):
        raise not_found()
    elif await fetch_one(
        "SELECT attempt_id FROM practice_submissions WHERE practice_id=%s "
        "AND owner_id=%s LIMIT 1 FOR SHARE",
        (row["practice_id"], row["owner_id"]),
        conn=conn,
    ):
        raise not_found()
    return PracticeView(
        practice_id=row["practice_id"],
        space_id=row["space_id"],
        scope_revision=row["scope_revision"],
        title=artifact.title
        if artifact
        else "练习生成中"
        if row["status"] == "generating"
        else "练习未生成",
        summary=artifact.summary if artifact else "",
        status=row["status"],
        revision=row["revision"],
        questions=[
            public_question(q, artifact.question_versions[q.id])
            for q in artifact.questions
        ]
        if artifact
        else [],
        scope=PublicResolvedScope.from_scope(scope),
        source_status="active",
        **progress,
    )


async def get_practice(owner_id: int, practice_id: str) -> PracticeView:
    async with transaction() as conn:
        row, request, scope = await authorize_practice(conn, owner_id, practice_id)
        return await _generation_view(conn, row, request, scope)


async def _task_practice_id(conn, owner_id, job):
    if job["kind"] == "practice_generate":
        request = generation_request(job["request"])
        row = await owned_practice(owner_id, request.practice_id, conn=conn)
        pinned, scope = _row_request_scope(row)
        require_generation_job(job, row, pinned, scope)
        return request.practice_id
    # Only scalar identities are projected for grade jobs in this stage. P03's
    # accepted get_practice_attempt helper will provide their eventual result.
    request = job.get("request")
    if not isinstance(request, dict):
        raise not_found()
    row = await fetch_one(
        "SELECT s.practice_id FROM practice_grading_requests g JOIN practice_submissions s "
        "ON s.attempt_id=g.attempt_id AND s.owner_id=g.owner_id "
        "WHERE g.grading_request_id=%s AND g.attempt_id=%s AND g.owner_id=%s",
        (request.get("grading_request_id"), request.get("attempt_id"), owner_id),
        conn=conn,
    )
    if row is None or request.get("practice_id") != row["practice_id"]:
        raise not_found()
    return row["practice_id"]


async def get_practice_task(owner_id: int, task_id: str) -> PracticeTaskView:
    from app.models.task_event import business_settled_from

    async with transaction() as conn:
        job = await owned_practice_task(owner_id, task_id, conn=conn, lock=True)
        practice_id = await _task_practice_id(conn, owner_id, job)
        result = None
        if job["status"] == "completed" and job["kind"] == "practice_generate":
            row, request, scope = await authorize_practice(
                conn, owner_id, practice_id, job=job
            )
            if row["generation_task_id"] != task_id:
                raise _generation_changed()
            result = await _generation_view(conn, row, request, scope)
        elif job["status"] == "completed" and job["kind"] == "practice_grade":
            from app.services.practice_answer_service import practice_attempt_view
            from app.services.practice_grading_service import checked_grading_task

            snapshot = await checked_grading_task(conn, owner_id, job)
            result = await practice_attempt_view(conn, owner_id, snapshot.attempt_id)
        code = job.get("error_code")
        code = code if isinstance(code, str) and _SAFE_CODE.fullmatch(code) else None
        return PracticeTaskView(
            task_id=task_id,
            practice_id=practice_id,
            operation="generate" if job["kind"] == "practice_generate" else "grade",
            status=job["status"],
            stage=job["stage"] if job["stage"] in _PUBLIC_STAGES else job["status"],
            error_code=code,
            error_message="任务未完成，请查看错误原因后重试" if code else None,
            business_settled=business_settled_from(job["status"], job["stage"]),
            result=result,
        )


async def cancel_practice_task(owner_id: int, task_id: str) -> PracticeTaskView:
    from app.workers.practice_job import reconcile_practice_job

    async with transaction() as conn:
        job = await owned_practice_task(owner_id, task_id, conn=conn, lock=True)
        await _task_practice_id(conn, owner_id, job)
        await job_service.cancel_job(owner_id, task_id, conn=conn)
        current = await owned_practice_task(owner_id, task_id, conn=conn, lock=True)
        await reconcile_practice_job(current, conn)
        await review_service.reconcile_review_generation(conn, current)
    return await get_practice_task(owner_id, task_id)


async def get_practice_evidence(owner_id: int, practice_id: str, evidence_id: str):
    async with transaction() as conn:
        row, request, scope = await authorize_practice(conn, owner_id, practice_id)
        artifact = await checked_practice_artifact(conn, row, request, scope)
        if not any(evidence_id in q.citation_refs for q in artifact.questions):
            raise not_found()
        evidence = next(
            (
                e
                for e in artifact.evidence_pack.evidence
                if e.evidence_id == evidence_id
            ),
            None,
        )
        if evidence is None:
            raise not_found()
        source = next((s for s in scope.documents if s.doc_id == evidence.doc_id), None)
        if source is None:
            raise not_found()
        try:
            canonical = source_service.artifacts().load_canonical(
                source.canonical_artifact_key
            )
        except (OSError, SourceUnavailable, ValueError) as exc:
            raise not_found() from exc
        if (
            canonical.owner_id != owner_id
            or canonical.namespace != scope.namespace
            or canonical.doc_id != evidence.doc_id
            or canonical.document_version_id != evidence.document_version_id
            or canonical.source_sha256 != evidence.locator.source_sha256
            or canonical.parse_artifact_id != evidence.parse_artifact_id
            or canonical.canonical_text_hash != evidence.locator.canonical_text_hash
            or canonical.text[evidence.locator.start_char : evidence.locator.end_char]
            != evidence.excerpt
        ):
            raise not_found()
        return evidence
