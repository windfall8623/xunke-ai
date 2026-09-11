"""Authorized UI reads; source hints and previews never create model calls."""

from decimal import Decimal

from app.core.config import get_settings
from app.core.db import fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import load
from app.models.practice_views import (
    PracticeCostPreview,
    PracticeReviewContext,
    PracticeReviewPoint,
    PublicPracticeEvidence,
)
from app.models.sources import PublicResolvedScope
from app.practice.contracts import PracticeSpec
from app.rag.budget import count_tokens
from app.rag.contracts import BudgetLimits
from app.rag.errors import SourceUnavailable
from app.rag.scope import evidence_in_scope
from app.services import learning_concept_service as concepts
from app.services import learning_scope_service as scopes
from app.services import (
    practice_answer_service,
    practice_service,
    provider_meter,
    source_service,
)


async def get_practice_evidence(owner_id, practice_id, question_id, evidence_id):
    async with transaction() as conn:
        row, request, scope = await practice_service.authorize_practice(
            conn, owner_id, practice_id
        )
        artifact = await practice_service.checked_practice_artifact(
            conn, row, request, scope
        )
        question = next(
            (item for item in artifact.questions if item.id == question_id), None
        )
        if question is None or evidence_id not in question.citation_refs:
            raise not_found()
        submitted = await fetch_one(
            "SELECT attempt_id FROM practice_submissions WHERE owner_id=%s AND practice_id=%s AND question_id=%s FOR SHARE",
            (owner_id, practice_id, question_id),
            conn=conn,
        )
        if submitted is None and load(row["help_usage_json"], {}).get(
            question_id, "none"
        ) not in {"hints", "unknown"}:
            raise conflict("help_ack_required", "请先确认查看资料提示")
        evidence = next(
            (
                item
                for item in artifact.evidence_pack.evidence
                if item.evidence_id == evidence_id
            ),
            None,
        )
        if evidence is None or not evidence_in_scope(evidence, scope):
            raise not_found()
        source = next(
            (item for item in scope.documents if item.doc_id == evidence.doc_id), None
        )
        if source is None:
            raise not_found()
        try:
            canonical = source_service.artifacts().load_canonical(
                source.canonical_artifact_key
            )
        except (OSError, ValueError, SourceUnavailable) as exc:
            raise not_found() from exc
        if (
            canonical.owner_id != owner_id
            or canonical.namespace != scope.namespace
            or canonical.doc_id != source.doc_id
            or canonical.document_version_id != source.document_version_id
            or canonical.parse_artifact_id != source.parse_artifact_id
            or canonical.source_sha256 != source.source_sha256
            or canonical.canonical_text_hash != source.canonical_text_hash
            or canonical.text[evidence.locator.start_char : evidence.locator.end_char]
            != evidence.excerpt
        ):
            raise not_found()
        return PublicPracticeEvidence(
            practice_id=practice_id,
            question_id=question_id,
            evidence_id=evidence_id,
            title=evidence.title,
            excerpt=evidence.excerpt,
            doc_id=evidence.doc_id,
            document_version_id=evidence.document_version_id,
            locator=evidence.locator,
        )


async def get_practice_review_context(actor, attempt_id):
    async with transaction() as conn:
        submission = await fetch_one(
            "SELECT practice_id FROM practice_submissions WHERE owner_id=%s AND attempt_id=%s",
            (actor.owner_id, attempt_id),
            conn=conn,
        )
        if submission is None:
            raise not_found()
        if "evaluator" not in actor.roles:
            raise AppError(403, "evaluator_required", "此操作需要本账号的评阅权限")
        row, request, scope = await practice_service.authorize_practice(
            conn, actor.owner_id, submission["practice_id"]
        )
        artifact = await practice_service.checked_practice_artifact(
            conn, row, request, scope
        )
        progress = await practice_answer_service.read_practice_progress(
            conn, row, artifact
        )
        attempt = next(
            (item for item in progress["submissions"] if item.attempt_id == attempt_id),
            None,
        )
        if attempt is None:
            raise not_found()
        question = next(
            (item for item in artifact.questions if item.id == attempt.question_id),
            None,
        )
        if question is None or question.type != "short_answer":
            raise conflict("review_not_supported", "只有已提交的短解释题需要人工复核")
        return PracticeReviewContext(
            practice_id=attempt.practice_id,
            attempt_id=attempt.attempt_id,
            question_id=attempt.question_id,
            question_version=attempt.question_version,
            stem=question.stem,
            answer=attempt.answer,
            rubric_version=question.rubric.version,
            criteria=[
                PracticeReviewPoint(
                    criterion_id=item.criterion_id,
                    reference_point=item.reference_point,
                    weight=item.weight,
                    evidence_refs=list(item.evidence_refs),
                )
                for item in question.rubric.criteria
            ],
            current_assessment_id=(
                attempt.current_assessment.assessment_id
                if attempt.current_assessment is not None
                else None
            ),
            grading_revision=attempt.grading_revision,
            help_usage=attempt.help_usage,
            scope=PublicResolvedScope.from_scope(scope),
        )


def calculate_practice_cost(body, config, settings):
    """Conservative complete generation + grading upper bound, never a bill."""
    grading_calls = (
        2 * body.question_count if "short_answer" in body.question_types else 0
    )
    generation_inputs = 5 * config.model_context_window
    generation_outputs = (
        4 * config.output_token_reserve + settings.reranker_llm_max_output_tokens
    )
    grading_output = getattr(settings, "practice_grading_output_tokens", 2048)
    grading_window = getattr(settings, "practice_grading_context_window", 32768)
    inputs = generation_inputs + grading_calls * grading_window
    outputs = generation_outputs + grading_calls * grading_output
    embeddings = BudgetLimits().max_embedding_calls * count_tokens(
        "；".join(body.objectives)
    )
    llm_cost = provider_meter.estimate("llm", inputs, outputs, reserve=True)
    embedding_cost = provider_meter.estimate("embedding", embeddings, 0)
    remote_cost = (
        0 if config.reranker.provider in {"none", "llm"} else settings.rerank_call_cny
    )
    known = all(item is not None for item in (llm_cost, embedding_cost, remote_cost))
    cost = (
        sum(
            (Decimal(str(item)) for item in (llm_cost, embedding_cost, remote_cost)),
            Decimal(0),
        )
        if known
        else None
    )
    return PracticeCostPreview(
        grading_llm_call_upper=grading_calls,
        input_token_upper=inputs,
        output_token_upper=outputs,
        embedding_token_upper=embeddings,
        cost_cny_upper=cost,
        cost_status="estimated" if known else "unknown",
        pricing_version=settings.pricing_version,
    )


async def preview_practice_cost(actor, body):
    body = PracticeSpec.model_validate(body.model_dump(mode="json"))
    async with transaction() as conn:
        space = await scopes.owned_space(
            actor.owner_id, body.space_id, conn=conn, lock=True
        )
        scopes.require_active(space)
        selected = await practice_service._concept_previews(actor.owner_id, body, conn)
        revisions = sorted(
            {
                body.scope_revision,
                space["title_scope_revision"],
                *(item["scope_revision"] for item in selected),
            }
        )
        fixed = [
            await scopes.stored_scope(
                actor.owner_id, body.space_id, revision, conn=conn
            )
            for revision in revisions
        ]
        await scopes.require_sources(fixed, conn=conn)
        for item in selected:
            current = await concepts.owned_concept(
                actor.owner_id, item["concept_id"], conn=conn, lock=True
            )
            if (current["scope_revision"], current["revision"]) != (
                item["scope_revision"],
                item["revision"],
            ):
                raise conflict("concept_scope_conflict", "概念已更新，请刷新后重试")
    _, config = practice_service._pipeline_selection()
    return calculate_practice_cost(body, config, get_settings())
