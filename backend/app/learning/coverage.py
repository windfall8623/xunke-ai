"""Fixed coverage for server-selected learning objectives, without a planner call."""

from __future__ import annotations

from pydantic import BaseModel, TypeAdapter

from app.learning.contracts import ObjectiveRef, Objectives
from app.rag.contracts import (
    CoveragePlan,
    CoverageTarget,
    QuizSpec,
    ResolvedScope,
    stable_hash,
)


_OBJECTIVES_ADAPTER = TypeAdapter(Objectives)


def _validation_data(value):
    """Revalidate nested models, including extras injected through model_copy."""
    if isinstance(value, BaseModel):
        return {key: _validation_data(item) for key, item in value}
    if isinstance(value, dict):
        return {key: _validation_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_validation_data(item) for item in value]
    return value


def build_learning_coverage(
    spec: QuizSpec, scope: ResolvedScope, objectives: Objectives
) -> tuple[CoveragePlan, dict[str, list[str]]]:
    """Preserve concept identities while keeping the legacy coverage JSON shape.

    Services authorize the supplied objectives and frozen scope. Targets inherit
    the scope's per-document section restrictions: a global section list would
    incorrectly exclude unrestricted documents in a mixed selection. Consumers
    must enforce that scope before binding evidence to these targets.
    """
    if not isinstance(spec, QuizSpec) or not isinstance(scope, ResolvedScope):
        raise ValueError("A QuizSpec and a server-resolved scope are required")
    if not isinstance(objectives, list) or any(
        not isinstance(objective, ObjectiveRef) for objective in objectives
    ):
        raise ValueError("Selected objectives must be ObjectiveRef values")
    spec = QuizSpec.model_validate(_validation_data(spec), strict=True)
    scope = ResolvedScope.model_validate(_validation_data(scope), strict=True)
    objectives = _OBJECTIVES_ADAPTER.validate_python(
        _validation_data(objectives), strict=True
    )
    if not scope.documents or not scope.namespace.strip():
        raise ValueError("Learning coverage requires a usable document scope")
    for source in scope.documents:
        identities = (
            source.doc_id,
            source.document_version_id,
            source.parse_artifact_id,
            source.index_build_id,
            source.attempt_id,
        )
        if any(not identity.strip() for identity in identities):
            raise ValueError("Source identities must not be blank")
        if len(set(source.section_ids)) != len(source.section_ids):
            raise ValueError("Duplicate source sections are not allowed")
    if any(not objective.concept_id.strip() for objective in objectives):
        raise ValueError("Concept identities must not be blank")

    quota, remainder = divmod(spec.question_count, len(objectives))
    scope_fingerprint = scope.fingerprint
    doc_ids = [source.doc_id for source in scope.documents]
    targets = []
    target_concepts = {}
    for index, objective in enumerate(objectives):
        target_id = "learning_" + stable_hash(
            {
                "concept_id": objective.concept_id,
                "scope_fingerprint": scope_fingerprint,
            }
        )
        targets.append(
            CoverageTarget(
                target_id=target_id,
                title=objective.title,
                doc_ids=doc_ids,
                question_quota=quota + (index < remainder),
            )
        )
        target_concepts[target_id] = [objective.concept_id]
    subqueries = list(
        dict.fromkeys(
            spec.user_input
            if objective.title == spec.user_input
            else spec.user_input + " " + objective.title
            for objective in objectives
        )
    )
    return (
        CoveragePlan(
            targets=targets,
            subqueries=subqueries,
            planner_version="deterministic-learning-v1",
        ),
        target_concepts,
    )
