"""Immutable learning scopes and the authorization gate for every derived read."""

from pydantic import ValidationError

from app.core.db import execute, fetch_one
from app.core.errors import AppError, conflict, not_found
from app.core.values import dump, load
from app.rag.contracts import RequestedScope, ResolvedScope
from app.rag.errors import ScopeRevoked, SourceUnavailable
from app.services import source_service


async def owned_space(owner_id, space_id, *, conn=None, lock=False):
    if lock and conn is None:
        raise ValueError("A space lock requires an existing transaction")
    row = await fetch_one(
        "SELECT * FROM learning_spaces WHERE space_id=%s AND owner_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (space_id, owner_id),
        conn=conn,
    )
    if not row:
        raise not_found()
    return row


def require_active(space):
    if space["status"] != "active":
        raise conflict("study_space_archived", "学习空间已归档，请先恢复后再开始新活动")


async def stored_scope(owner_id, space_id, scope_revision, *, conn=None):
    """Load source facts only. Callers must authorize before using derived text."""
    row = await fetch_one(
        "SELECT scope_json,scope_fingerprint FROM learning_scope_revisions "
        "WHERE space_id=%s AND revision=%s AND owner_id=%s",
        (space_id, scope_revision, owner_id),
        conn=conn,
    )
    if not row:
        raise not_found()
    try:
        scope = ResolvedScope.model_validate(load(row["scope_json"]))
    except (ValidationError, ValueError, TypeError) as exc:
        raise not_found() from exc
    if (
        scope.owner_id != owner_id
        or scope.namespace != "production"
        or not scope.documents
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


async def require_sources(scopes: list[ResolvedScope], *, conn=None) -> None:
    """Authorize complete production scopes in global document lock order.

    Call after locking learning space/activity roots and before dependent rows.
    Every original scope is validated before source locks. Evaluation copies
    with lineage parents are excluded: the only lineage writer creates sources
    in evaluation namespaces, which are not valid learning scopes.
    Single-document checks retain every version/build/chapter distinction and
    allow a union larger than the five-document limit of each saved scope.
    """
    validated = [
        ResolvedScope.model_validate(
            scope.model_dump(mode="json") if isinstance(scope, ResolvedScope) else scope
        )
        for scope in scopes
    ]
    if not validated or any(
        scope.namespace != "production" or not scope.documents for scope in validated
    ):
        raise not_found()
    dependencies = [
        (scope, source) for scope in validated for source in scope.documents
    ]
    for scope, source in sorted(
        dependencies, key=lambda item: (item[1].doc_id, dump(item[1]))
    ):
        await require_source(
            ResolvedScope(
                owner_id=scope.owner_id,
                namespace=scope.namespace,
                documents=[source],
            ),
            conn=conn,
        )


async def quiz_sources_available(owner_id, quiz, *, conn=None):
    """Gate legacy quiz reads with both activity and linked-space provenance."""
    if quiz.get("source_status") == "source_revoked":
        return False
    raw = load(quiz.get("source_scope_json"))
    if raw:
        try:
            scope = ResolvedScope.model_validate(raw)
        except (ValidationError, ValueError, TypeError):
            return False
        if scope.owner_id != owner_id or scope.namespace != "production":
            return False
    link = await fetch_one(
        "SELECT space_id,scope_revision FROM learning_quiz_contexts WHERE quiz_id=%s AND owner_id=%s",
        (quiz["quiz_id"], owner_id),
        conn=conn,
    )
    if link:
        try:
            space_scope = await read_scope(
                owner_id, link["space_id"], link["scope_revision"], conn=conn
            )
        except AppError as exc:
            if exc.status == 404:
                return False
            raise
        if not raw or not scope_covers(space_scope, scope):
            return False
    if raw and not await scope_available(scope, conn=conn):
        return False
    return True


async def require_quiz_sources(owner_id, quiz, *, conn=None):
    if not await quiz_sources_available(owner_id, quiz, conn=conn):
        raise AppError(404, "source_revoked", "关联资料已删除或授权已变更")


async def lock_quiz_space(owner_id, quiz_id, *, conn):
    """Locate the immutable link first so linked answer writes lock space first."""
    link = await fetch_one(
        "SELECT space_id FROM learning_quiz_contexts WHERE quiz_id=%s AND owner_id=%s",
        (quiz_id, owner_id),
        conn=conn,
    )
    if link:
        await owned_space(owner_id, link["space_id"], conn=conn, lock=True)


async def read_scope(
    owner_id: int,
    space_id: str,
    scope_revision: int,
    *,
    conn=None,
    lock: bool = False,
) -> ResolvedScope:
    await owned_space(owner_id, space_id, conn=conn, lock=lock)
    scope = await stored_scope(owner_id, space_id, scope_revision, conn=conn)
    await require_source(scope, conn=conn)
    return scope


def scope_covers(space_scope, activity_scope) -> bool:
    """Require every activity source/version/section within the saved space.

    A space can contain extra material. An activity's full-document selection
    cannot be justified by a space that only authorizes selected chapters.
    """
    space_scope = ResolvedScope.model_validate(space_scope)
    activity_scope = ResolvedScope.model_validate(activity_scope)
    if (
        not activity_scope.documents
        or space_scope.owner_id != activity_scope.owner_id
        or space_scope.namespace != activity_scope.namespace
    ):
        return False
    by_id = {source.doc_id: source for source in space_scope.documents}
    for source in activity_scope.documents:
        allowed = by_id.get(source.doc_id)
        if allowed is None:
            return False
        excluded = {"title", "section_ids", "section_catalog_revision"}
        if source.model_dump(exclude=excluded) != allowed.model_dump(exclude=excluded):
            return False
        if allowed.section_ids and (
            not source.section_ids
            or not set(source.section_ids) <= set(allowed.section_ids)
        ):
            return False
    return True


async def save_scope(conn, owner_id, space_id, scope_revision, scope):
    """Append a full snapshot while the caller holds the owned space root lock."""
    scope = ResolvedScope.model_validate(scope)
    if (
        scope.owner_id != owner_id
        or scope.namespace != "production"
        or not scope.documents
    ):
        raise not_found()
    await require_source(scope, conn=conn)
    await execute(
        "INSERT INTO learning_scope_revisions(space_id,revision,owner_id,scope_json,scope_fingerprint) "
        "VALUES(%s,%s,%s,%s,%s)",
        (space_id, scope_revision, owner_id, dump(scope), scope.fingerprint),
        conn=conn,
    )
    for source in sorted(scope.documents, key=lambda item: item.doc_id):
        await execute(
            "INSERT INTO learning_scope_sources(space_id,scope_revision,owner_id,doc_id,document_version_id,"
            "parse_artifact_id,index_build_id,authorization_revision,source_sha256,canonical_text_hash,"
            "section_catalog_revision,section_ids_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                space_id,
                scope_revision,
                owner_id,
                source.doc_id,
                source.document_version_id,
                source.parse_artifact_id,
                source.index_build_id,
                source.authorization_revision,
                source.source_sha256,
                source.canonical_text_hash,
                source.section_catalog_revision,
                dump(source.section_ids),
            ),
            conn=conn,
        )


def select_unit_scope(scope, requested, *, catalogs) -> ResolvedScope:
    """Select chapters from the saved scope, never from today's active build."""
    scope = ResolvedScope.model_validate(scope)
    requested = RequestedScope.model_validate(requested)
    by_id = {source.doc_id: source for source in scope.documents}
    selected_sources = []
    for selected in sorted(requested.documents, key=lambda item: item.doc_id):
        source = by_id.get(selected.doc_id)
        if source is None:
            raise not_found()
        if selected.section_catalog_revision not in (None, source.parse_artifact_id):
            raise conflict("section_catalog_changed", "章节目录不属于此学习范围版本")
        if selected.section_ids:
            if selected.section_catalog_revision != source.parse_artifact_id:
                raise conflict(
                    "section_catalog_changed", "章节目录不属于此学习范围版本"
                )
            if not set(selected.section_ids) <= catalogs.get(source.doc_id, set()):
                raise not_found()
        if source.section_ids and (
            not selected.section_ids
            or not set(selected.section_ids) <= set(source.section_ids)
        ):
            raise not_found()
        selected_sources.append(
            source.model_copy(
                update={
                    "section_ids": sorted(selected.section_ids),
                    "section_catalog_revision": source.parse_artifact_id
                    if selected.section_ids
                    else source.section_catalog_revision,
                }
            )
        )
    return ResolvedScope(
        owner_id=scope.owner_id, namespace=scope.namespace, documents=selected_sources
    )


def checked_unit_selection(scope, requested) -> RequestedScope:
    catalogs = {}
    selected_ids = {item.doc_id for item in requested.documents}
    for source in scope.documents:
        if source.doc_id not in selected_ids:
            continue
        canonical = source_service.artifacts().load_canonical(
            source.canonical_artifact_key
        )
        if (
            canonical.owner_id,
            canonical.namespace,
            canonical.doc_id,
            canonical.document_version_id,
            canonical.parse_artifact_id,
            canonical.source_sha256,
            canonical.canonical_text_hash,
        ) != (
            scope.owner_id,
            scope.namespace,
            source.doc_id,
            source.document_version_id,
            source.parse_artifact_id,
            source.source_sha256,
            source.canonical_text_hash,
        ):
            raise not_found()
        catalogs[source.doc_id] = {section.section_id for section in canonical.sections}
    selected_scope = select_unit_scope(scope, requested, catalogs=catalogs)
    return RequestedScope(
        documents=[
            {
                "doc_id": source.doc_id,
                "section_ids": source.section_ids,
                "section_catalog_revision": source.parse_artifact_id
                if source.section_ids
                else None,
            }
            for source in selected_scope.documents
        ]
    )
