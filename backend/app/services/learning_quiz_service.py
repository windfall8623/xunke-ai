"""Server-owned QA origins and concept mappings around legacy quiz artifacts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.core.db import execute, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump
from app.learning.contracts import LearningId, Objectives, QuestionConceptBinding
from app.learning.coverage import build_learning_coverage
from app.learning.quiz_identity import canonical_quiz_question_version
from app.models.study import StudyQuizFromQaBody
from app.rag.contracts import (
    Contract,
    CoveragePlan,
    Hash,
    Identity,
    QuizPayload,
    QuizSpec,
    RequestedScope,
    ResolvedScope,
)
from app.rag.errors import GenerationValidationFailed
from app.rag.validation import validate_quiz_artifact
from app.services import job_service, learning_concept_service, qa_practice_source
from app.services import learning_scope_service as scopes


class QaQuizOrigin(Contract):
    kind: Literal["qa"] = "qa"
    answer_id: LearningId
    session_id: LearningId
    scope_revision: int = Field(ge=1)
    artifact_hash: Hash
    block_ids: list[Identity] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def unique_fact_blocks(self):
        if len(self.block_ids) != len(set(self.block_ids)):
            raise ValueError("QA origin fact blocks must be unique")
        return self


class ReviewQuizOrigin(Contract):
    kind: Literal["review"] = "review"
    review_task_ids: list[LearningId] = Field(min_length=1, max_length=3)
    expected_revisions: dict[LearningId, Annotated[int, Field(ge=1)]]
    task_id: LearningId
    quiz_id: LearningId
    concept_scope_revisions: dict[LearningId, Annotated[int, Field(ge=1)]]
    space_title_scope_revision: int = Field(ge=1)

    @model_validator(mode="after")
    def complete_occurrence_identity(self):
        if len(self.review_task_ids) != len(set(self.review_task_ids)) or set(
            self.review_task_ids
        ) != set(self.expected_revisions):
            raise ValueError("Every review occurrence requires its frozen revision")
        return self


class LearningQuizContext(Contract):
    """Private task envelope; never a field of QuizSpec or QuizArtifact."""

    space_id: LearningId
    scope_revision: int = Field(ge=1)
    unit_id: LearningId | None = None
    objectives: Objectives
    coverage_plan: CoveragePlan
    target_concepts: dict[Identity, list[LearningId]]
    origin: Annotated[QaQuizOrigin | ReviewQuizOrigin, Field(discriminator="kind")]

    @model_validator(mode="after")
    def exact_objective_mapping(self):
        targets = [target.target_id for target in self.coverage_plan.targets]
        concepts = [objective.concept_id for objective in self.objectives]
        if (
            len(targets) != len(set(targets))
            or len(targets) != len(concepts)
            or set(self.target_concepts) != set(targets)
            or any(len(ids) != 1 for ids in self.target_concepts.values())
            or [self.target_concepts[target][0] for target in targets] != concepts
        ):
            raise ValueError(
                "Every selected objective requires its own exact target mapping"
            )
        if isinstance(self.origin, ReviewQuizOrigin) and set(
            self.origin.concept_scope_revisions
        ) != set(concepts):
            raise ValueError(
                "Review origins preserve every selected concept's provenance"
            )
        return self


def qa_request_hash(body: StudyQuizFromQaBody) -> str:
    """Identify user intent without looking up today's active source revision."""
    body = StudyQuizFromQaBody.model_validate(body)
    request = body.model_dump(mode="json")
    request["block_ids"] = sorted(request["block_ids"])
    return digest(dump({"entrypoint": "study.quiz.from_qa", "request": request}))


def learning_request_hash(spec: QuizSpec, context: LearningQuizContext) -> str:
    """The resolved enqueue path reconstructs the same semantic replay identity."""
    if isinstance(context.origin, ReviewQuizOrigin):
        from app.models.study import ReviewQuizBody
        from app.services.review_service import review_request_hash

        return review_request_hash(
            ReviewQuizBody(
                review_task_ids=context.origin.review_task_ids,
                expected_revisions=context.origin.expected_revisions,
                question_count=spec.question_count,
                difficulty=spec.difficulty,
            )
        )
    return qa_request_hash(
        StudyQuizFromQaBody(
            answer_id=context.origin.answer_id,
            block_ids=context.origin.block_ids,
            space_id=context.space_id,
            scope_revision=context.scope_revision,
            objectives=context.objectives,
            question_count=spec.question_count,
            difficulty=spec.difficulty,
        )
    )


def requested_scope(scope: ResolvedScope) -> RequestedScope:
    """Describe the frozen selection without resolving its active builds again."""
    return RequestedScope(
        documents=[
            {
                "doc_id": source.doc_id,
                "section_ids": source.section_ids,
                "section_catalog_revision": source.parse_artifact_id
                if source.section_ids
                else None,
            }
            for source in scope.documents
        ]
    )


def validate_learning_context(spec, scope, context) -> LearningQuizContext:
    """Reject incomplete or altered mappings before retrieval or publication."""
    try:
        spec = QuizSpec.model_validate(spec)
        scope = ResolvedScope.model_validate(scope)
        context = LearningQuizContext.model_validate(
            context.model_dump(mode="json")
            if isinstance(context, LearningQuizContext)
            else context
        )
        plan, mapping = build_learning_coverage(spec, scope, context.objectives)
        if (
            scope.namespace != "production"
            or spec.source_policy != "strict_docs"
            or spec.scope != requested_scope(scope)
            or context.coverage_plan != plan
            or context.target_concepts != mapping
            or spec.objective_titles
            != [objective.title for objective in context.objectives]
        ):
            raise ValueError(
                "Learning coverage differs from its frozen source and objectives"
            )
    except (ValueError, TypeError, AttributeError) as exc:
        raise AppError(
            422, "invalid_learning_context", "练习学习上下文与固定来源不一致"
        ) from exc
    return context


def _qa_origin(qa_context) -> QaQuizOrigin:
    return QaQuizOrigin(
        answer_id=qa_context.answer_id,
        session_id=qa_context.session_id,
        scope_revision=qa_context.scope_revision,
        artifact_hash=qa_context.artifact_hash,
        block_ids=sorted(block.block_id for block in qa_context.selected_fact_blocks),
    )


async def authorize_context(
    owner_id: int,
    spec: QuizSpec,
    scope: ResolvedScope,
    context: LearningQuizContext,
    *,
    conn=None,
    require_active: bool = True,
    lock_concepts: bool = True,
) -> LearningQuizContext:
    """Authorize all frozen dependencies in one globally ordered source pass.

    Publication already holds its task lease. The space lock comes next, then
    sources and concept rows. A prior RR snapshot may contain old provenance;
    compare the current locked concepts after authorizing the preview scopes.
    """
    context = validate_learning_context(spec, scope, context)
    if scope.owner_id != owner_id:
        raise not_found()
    if isinstance(context.origin, ReviewQuizOrigin):
        from app.services.review_service import authorize_review_quiz_context

        await authorize_review_quiz_context(
            owner_id,
            spec,
            scope,
            context,
            conn=conn,
            require_active=require_active,
            lock_concepts=lock_concepts,
        )
        return context
    if conn is None:
        async with transaction() as tx:
            return await authorize_context(
                owner_id,
                spec,
                scope,
                context,
                conn=tx,
                require_active=require_active,
                lock_concepts=lock_concepts,
            )
    space = await scopes.owned_space(owner_id, context.space_id, conn=conn, lock=True)
    if require_active:
        scopes.require_active(space)
    # The from-QA endpoint does not submit units. Do not accept an injected unit
    # association without the separate unit selection and provenance workflow.
    if context.unit_id is not None:
        raise not_found()
    space_scope = await scopes.stored_scope(
        owner_id, context.space_id, context.scope_revision, conn=conn
    )
    if not scopes.scope_covers(space_scope, scope):
        raise conflict("study_scope_mismatch", "所选学习范围未覆盖回答的完整来源版本")
    previews = []
    for concept_id in sorted(objective.concept_id for objective in context.objectives):
        concept = await learning_concept_service.owned_concept(
            owner_id, concept_id, conn=conn
        )
        if concept["space_id"] != context.space_id:
            raise not_found()
        previews.append(concept)
    dependencies = [scope, space_scope]
    provenance_revisions = {space["title_scope_revision"]} | {
        concept["scope_revision"] for concept in previews
    }
    for revision in sorted(provenance_revisions):
        dependencies.append(
            await scopes.stored_scope(owner_id, context.space_id, revision, conn=conn)
        )
    await scopes.require_sources(dependencies, conn=conn)
    qa_context = await qa_practice_source.load_context(
        owner_id, context.origin.answer_id, context.origin.block_ids, conn=conn
    )
    if (
        qa_context.scope.fingerprint != scope.fingerprint
        or _qa_origin(qa_context) != context.origin
        or qa_context.retrieval_query != spec.user_input
    ):
        raise not_found()
    if lock_concepts:
        for preview in previews:
            current = await learning_concept_service.owned_concept(
                owner_id, preview["concept_id"], conn=conn, lock=True
            )
            if any(
                current[field] != preview[field]
                for field in ("space_id", "scope_revision", "revision")
            ):
                raise conflict("concept_revision_conflict", "概念已更新，请刷新后重试")
    return context


async def authorize_job(
    owner_id, job, *, conn=None, require_active=True, lock_concepts=True
):
    from app.services.quiz_service import parse_quiz_request

    if (
        job["user_id"] != owner_id
        or job["kind"] != "quiz"
        or job["mode"] != "production"
    ):
        raise not_found()
    if not job.get("request"):
        # Cleanup retains the durable identity and frozen scope while removing
        # source-derived request text. It is no longer a runnable envelope.
        raise AppError(404, "source_revoked", "关联资料已删除或授权已变更")
    spec, context = parse_quiz_request(job["request"])
    if context is None or not job.get("scope"):
        raise not_found()
    scope = ResolvedScope.model_validate(job["scope"])
    context = validate_learning_context(spec, scope, context)
    if learning_request_hash(spec, context) != job["request_hash"]:
        raise conflict("learning_request_changed", "练习请求与已保存的学习上下文不一致")
    await authorize_context(
        owner_id,
        spec,
        scope,
        context,
        conn=conn,
        require_active=require_active,
        lock_concepts=lock_concepts,
    )
    return spec, scope, context


async def create_from_qa(actor, body: StudyQuizFromQaBody, key):
    """Create a legacy objective quiz using the checked answer's original scope."""
    from app.services.quiz_service import enqueue_resolved_quiz

    body = StudyQuizFromQaBody.model_validate(body)
    old = await job_service.existing_job(
        actor.owner_id, "quiz", key, qa_request_hash(body)
    )
    if old:
        await authorize_job(actor.owner_id, old, require_active=False)
        return await job_service.get_task(actor.owner_id, old["task_id"])
    qa_context = await qa_practice_source.load_context(
        actor.owner_id, body.answer_id, body.block_ids
    )
    spec = QuizSpec(
        user_input=qa_context.retrieval_query,
        question_count=body.question_count,
        difficulty=body.difficulty,
        source_policy="strict_docs",
        scope=requested_scope(qa_context.scope),
        objective_titles=[objective.title for objective in body.objectives],
    )
    plan, mapping = build_learning_coverage(spec, qa_context.scope, body.objectives)
    context = LearningQuizContext(
        space_id=body.space_id,
        scope_revision=body.scope_revision,
        objectives=body.objectives,
        coverage_plan=plan,
        target_concepts=mapping,
        origin=_qa_origin(qa_context),
    )
    return await enqueue_resolved_quiz(
        actor, spec, qa_context.scope, key, learning_context=context
    )


async def publish_context(conn, owner_id, quiz_id, spec, scope, context, artifact):
    """Save context and verified bindings in the quiz publication transaction."""
    if conn is None:
        raise ValueError("Learning quiz publication requires an existing transaction")
    # bind_questions performs the final current-provenance comparison after its
    # source checks. Avoid holding concept locks across those source checks.
    context = await authorize_context(
        owner_id, spec, scope, context, conn=conn, lock_concepts=False
    )
    pack = artifact.evidence_pack
    actual_plan = pack.coverage.model_copy(deep=True) if pack.coverage else None
    if actual_plan:
        for target in actual_plan.targets:
            target.evidence_ids = []
    payload = {name: getattr(artifact, name) for name in QuizPayload.model_fields}
    validation = validate_quiz_artifact(payload, spec, pack)
    if (
        artifact.owner_id != owner_id
        or artifact.mode != "production"
        or not artifact.validation.passed
        or not validation.passed
        or pack.resolved_scope.fingerprint != scope.fingerprint
        or actual_plan != context.coverage_plan
    ):
        raise GenerationValidationFailed(
            "Quiz artifact does not match the frozen learning context"
        )
    bindings = [
        QuestionConceptBinding(
            question_id=question.id,
            question_version=canonical_quiz_question_version(question, pack),
            concept_ids=context.target_concepts[question.coverage_target_id],
        )
        for question in artifact.questions
    ]
    await execute(
        "INSERT INTO learning_quiz_contexts(quiz_id,owner_id,space_id,scope_revision,unit_id,"
        "source_scope_json,scope_fingerprint,objectives_json,coverage_plan_json,target_concepts_json,origin_json) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            quiz_id,
            owner_id,
            context.space_id,
            context.scope_revision,
            context.unit_id,
            dump(scope),
            scope.fingerprint,
            dump(
                [objective.model_dump(mode="json") for objective in context.objectives]
            ),
            dump(pack.coverage),
            dump(context.target_concepts),
            dump(context.origin),
        ),
        conn=conn,
    )
    await learning_concept_service.bind_questions(
        conn,
        owner_id,
        origin_kind="quiz",
        origin_id=quiz_id,
        space_id=context.space_id,
        scope_revision=context.scope_revision,
        question_concepts=bindings,
    )
