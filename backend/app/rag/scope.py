"""Normalize public requests and enforce the explicit source whitelist."""

from pydantic import ValidationError

from app.rag.contracts import (
    ActorContext,
    DocumentEvidence,
    QuizSpec,
    ResolvedScope,
    SourceManifest,
)
from app.rag.errors import InvalidScope, ScopeRevoked, SourceUnavailable


def normalize_spec(payload: dict | QuizSpec) -> QuizSpec:
    try:
        return (
            payload
            if isinstance(payload, QuizSpec)
            else QuizSpec.model_validate(payload)
        )
    except (ValidationError, ValueError) as exc:
        raise InvalidScope("Invalid or ambiguous source selection") from exc


def resolve_scope(
    spec: QuizSpec, actor: ActorContext, namespace: str, manifests: list[SourceManifest]
) -> ResolvedScope:
    """Apply selection to already authorized ready manifests, never query all docs.

    The SQL service must supply only accepted ready builds and recheck revisions.
    Every requested document must be found: missing/unauthorized items are not dropped.
    """
    if spec.source_policy == "topic":
        if manifests:
            raise InvalidScope("Topic mode cannot receive private source manifests")
        return ResolvedScope(owner_id=actor.owner_id, namespace=namespace)
    if spec.scope is None:
        raise InvalidScope("Document mode needs an explicit selection")
    by_id = {m.doc_id: m for m in manifests}
    selected = []
    for request in spec.scope.documents:
        source = by_id.get(request.doc_id)
        if (
            source is None
            or source.owner_id != actor.owner_id
            or source.namespace != namespace
        ):
            raise ScopeRevoked("Source is unavailable")
        if (
            request.section_catalog_revision
            and request.section_catalog_revision != source.parse_artifact_id
        ):
            raise SourceUnavailable("Section catalog changed; refresh the selection")
        if source.section_ids and not set(request.section_ids).issubset(
            source.section_ids
        ):
            raise ScopeRevoked("Selected section is unavailable")
        selected.append(
            source.model_copy(
                update={
                    "section_ids": request.section_ids,
                    "section_catalog_revision": request.section_catalog_revision,
                }
            )
        )
    return ResolvedScope(
        owner_id=actor.owner_id, namespace=namespace, documents=selected
    )


def require_scope(
    actor: ActorContext, scope: ResolvedScope, *, namespace: str | None = None
) -> None:
    if scope.owner_id != actor.owner_id or (
        namespace is not None and scope.namespace != namespace
    ):
        raise ScopeRevoked("Source scope is unavailable")


def require_execution_scope(actor, context, scope: ResolvedScope) -> None:
    """Validate the process mode before a private artifact or provider is read."""
    require_scope(actor, scope, namespace=context.storage_namespace)
    if context.mode == "production" and scope.namespace != "production":
        raise ScopeRevoked("Production execution requires production sources")
    if context.mode == "evaluation":
        if "admin" not in actor.roles:
            raise ScopeRevoked("System model admin permission is required")
        if scope.namespace != "evaluation" and not scope.namespace.startswith(
            "evaluation:"
        ):
            raise ScopeRevoked("Evaluation requires an isolated source namespace")


def evidence_in_scope(evidence, scope: ResolvedScope) -> bool:
    if evidence.owner_id != scope.owner_id or evidence.namespace != scope.namespace:
        return False
    if not isinstance(evidence, DocumentEvidence):
        return True
    for source in scope.documents:
        if (
            evidence.doc_id,
            evidence.document_version_id,
            evidence.parse_artifact_id,
            evidence.index_build_id,
            evidence.attempt_id,
            evidence.locator.source_sha256,
            evidence.locator.canonical_text_hash,
        ) != (
            source.doc_id,
            source.document_version_id,
            source.parse_artifact_id,
            source.index_build_id,
            source.attempt_id,
            source.source_sha256,
            source.canonical_text_hash,
        ):
            continue
        return not source.section_ids or bool(
            set(source.section_ids)
            & {evidence.locator.section_id, *evidence.locator.section_ids}
        )
    return False
