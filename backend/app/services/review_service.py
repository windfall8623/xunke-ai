"""Authorized review reads and the shared quiz/practice occurrence transaction.

Generation callers create and lock their durable job before claiming. This
module does not call a model or treat generation success as learning evidence.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, load, uid
from app.models.study import ReviewQuizBody, ReviewUpdateBody
from app.rag.contracts import ResolvedScope
from app.services import learning_concept_service as concepts
from app.services import learning_scope_service as scopes


UTC = timezone.utc
_IMMUTABLE_REVIEW = (
    "owner_id",
    "space_id",
    "scope_revision",
    "concept_id",
    "schedule_seq",
)


def utc(value):
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def timestamp(value):
    return utc(value).isoformat().replace("+00:00", "Z") if value is not None else None


def sql_time(value):
    return utc(value).replace(tzinfo=None)


def _aware_filter(value):
    try:
        parsed = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
        if (
            not isinstance(parsed, datetime)
            or parsed.tzinfo is None
            or parsed.utcoffset() is None
        ):
            raise ValueError("aware time required")
        return parsed.astimezone(UTC)
    except (TypeError, ValueError, AttributeError) as exc:
        raise AppError(422, "invalid_filter", "日期时间必须包含时区") from exc


def page_context(owner_id, resource, filters):
    return digest(
        dump({"owner_id": owner_id, "resource": resource, "filters": filters})
    )


def read_cursor(cursor, context, limit):
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise AppError(422, "invalid_limit", "每页条数须为 1–100")
    if cursor is None:
        return None
    try:
        if not isinstance(cursor, str) or len(cursor) > 2048:
            raise ValueError("invalid cursor length")
        raw = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
        )
        value = json.loads(raw)
        if (
            set(value) != {"v", "context", "time", "id", "cutoff"}
            or value["v"] != 1
            or value["context"] != context
        ):
            raise ValueError("cursor belongs to another query")
        if not isinstance(value["id"], str) or not 1 <= len(value["id"]) <= 256:
            raise ValueError("invalid position")
        value["time"] = _aware_filter(value["time"])
        if value["cutoff"] is not None:
            value["cutoff"] = _aware_filter(value["cutoff"])
        return value
    except (ValueError, TypeError, KeyError, AppError) as exc:
        raise AppError(422, "invalid_cursor", "分页位置已失效，请重新加载") from exc


def write_cursor(context, when, identity, *, cutoff=None):
    value = {
        "v": 1,
        "context": context,
        "time": timestamp(when),
        "id": identity,
        "cutoff": timestamp(cutoff),
    }
    return base64.urlsafe_b64encode(dump(value).encode()).decode().rstrip("=")


def _require_transaction(conn):
    if conn is None or not conn.get_transaction_status():
        raise ValueError("Review operations require the caller's transaction")


@dataclass(frozen=True)
class ReviewBatch:
    space: dict
    scope: ResolvedScope
    concepts: tuple[dict, ...]
    reviews: tuple[dict, ...]

    @property
    def concept_ids(self):
        return [row["concept_id"] for row in self.concepts]


async def _review_rows(owner_id, review_task_ids, *, conn=None, lock=False):
    ids = sorted(review_task_ids)
    if not ids or len(ids) > 3 or len(ids) != len(set(ids)):
        raise AppError(422, "invalid_review_batch", "每批请选择 1–3 个不同的复习任务")
    rows = await fetch_all(
        "SELECT * FROM review_tasks WHERE owner_id=%s AND review_task_id IN ("
        + ",".join(["%s"] * len(ids))
        + ") ORDER BY review_task_id"
        + (" FOR UPDATE" if lock else ""),
        (owner_id, *ids),
        conn=conn,
    )
    if len(rows) != len(ids):
        raise not_found()
    return list(rows)


async def authorize_review_batch(
    conn,
    owner_id,
    review_task_ids,
    *,
    require_active=True,
    scope=None,
    provenance_revisions=(),
    lock_reviews=True,
    lock_concepts=True,
    practice_id=None,
):
    """Lock space, optional practice root, all sources, concepts/state, reviews.

    Frozen source revisions are never replaced by today's active revision.
    Saved metadata provenance may be supplied by a generation envelope so that
    renaming a concept cannot authorize text copied from its former source.
    """
    _require_transaction(conn)
    preview = await _review_rows(owner_id, review_task_ids, conn=conn)
    space_ids = {row["space_id"] for row in preview}
    revisions = {row["scope_revision"] for row in preview}
    concept_ids = sorted(row["concept_id"] for row in preview)
    if (
        len(space_ids) != 1
        or len(revisions) != 1
        or len(set(concept_ids)) != len(concept_ids)
    ):
        raise conflict("review_scope_mismatch", "请按同一空间和同一来源版本分批复习")
    space_id, revision = next(iter(space_ids)), next(iter(revisions))
    space = await scopes.owned_space(owner_id, space_id, conn=conn, lock=True)
    if require_active:
        scopes.require_active(space)
    if practice_id is not None:
        root = await fetch_one(
            "SELECT practice_id,space_id,scope_revision FROM practice_sessions WHERE practice_id=%s AND owner_id=%s FOR UPDATE",
            (practice_id, owner_id),
            conn=conn,
        )
        if root is None or (root["space_id"], root["scope_revision"]) != (
            space_id,
            revision,
        ):
            raise not_found()
    fixed = await scopes.stored_scope(owner_id, space_id, revision, conn=conn)
    if scope is not None and ResolvedScope.model_validate(scope) != fixed:
        raise conflict("review_scope_mismatch", "复习来源版本与任务保存的范围不一致")
    previews = [
        await concepts.owned_concept(owner_id, concept_id, conn=conn)
        for concept_id in concept_ids
    ]
    if any(row["space_id"] != space_id for row in previews):
        raise not_found()
    required = {
        revision,
        space["title_scope_revision"],
        *provenance_revisions,
        *(row["scope_revision"] for row in previews),
    }
    if None in required:
        raise not_found()
    dependencies = [
        await scopes.stored_scope(owner_id, space_id, version, conn=conn)
        for version in sorted(required)
    ]
    await scopes.require_sources(dependencies, conn=conn)
    current_concepts = []
    for previous in previews:
        if not lock_concepts:
            current_concepts.append(previous)
            continue
        current = await concepts.owned_concept(
            owner_id, previous["concept_id"], conn=conn, lock=True
        )
        if any(
            current[field] != previous[field]
            for field in ("space_id", "scope_revision", "revision")
        ):
            raise conflict("concept_revision_conflict", "概念已更新，请刷新后重试")
        current_concepts.append(current)
    if lock_reviews:
        for concept_id in concept_ids:
            state = await fetch_one(
                "SELECT revision FROM learner_concept_state WHERE owner_id=%s AND space_id=%s AND concept_id=%s AND scope_revision=%s FOR UPDATE",
                (owner_id, space_id, concept_id, revision),
                conn=conn,
            )
            if state is None:
                raise not_found()
        rows = await _review_rows(owner_id, review_task_ids, conn=conn, lock=True)
        for current, previous in zip(rows, preview, strict=True):
            if any(current[field] != previous[field] for field in _IMMUTABLE_REVIEW):
                raise conflict(
                    "review_revision_conflict", "复习安排已更新，请刷新后重试"
                )
    else:
        rows = preview
    return ReviewBatch(space, fixed, tuple(current_concepts), tuple(rows))


async def preview_review_batch(owner_id, review_task_ids):
    """Read an authorized fixed batch before constructing a durable request."""
    async with transaction() as conn:
        return await authorize_review_batch(
            conn, owner_id, review_task_ids, lock_reviews=False
        )


def review_view(row, *, space=None, concept=None, available=True):
    return {
        "review_task_id": row["review_task_id"],
        "space_id": row["space_id"],
        "scope_revision": row["scope_revision"],
        "concept_id": row["concept_id"],
        "space_title": space["title"]
        if available and space
        else "资料已失效的学习空间",
        "concept_title": concept["title"]
        if available and concept
        else "资料已失效的概念",
        "timezone": space["timezone"] if space else "Asia/Shanghai",
        "schedule_seq": row["schedule_seq"],
        "revision": row["revision"],
        "status": row["status"],
        "paused": bool(row["paused"]),
        "is_current": row["is_current"] == 1,
        "rule_version": row["rule_version"],
        "rule_due_at": timestamp(row["rule_due_at"]),
        "due_at": timestamp(row["due_at"]),
        "override_due_at": timestamp(row["override_due_at"]),
        "task_id": row["task_id"],
        "origin_kind": row["origin_kind"],
        "origin_id": row["origin_id"],
        "last_error_code": row["last_error_code"],
        "claimed_at": timestamp(row["claimed_at"]),
        "completed_at": timestamp(row["completed_at"]),
        "source_status": "active" if available else "revoked",
    }


async def authorized_review_view(owner_id, row):
    try:
        async with transaction() as conn:
            batch = await authorize_review_batch(
                conn,
                owner_id,
                [row["review_task_id"]],
                require_active=False,
                lock_reviews=False,
            )
            return review_view(row, space=batch.space, concept=batch.concepts[0])
    except AppError as exc:
        if exc.status != 404:
            raise
        return review_view(row, available=False)


async def list_due_reviews(actor, filters=None, cursor=None, limit=20):
    filters = {
        key: value for key, value in dict(filters or {}).items() if value is not None
    }
    allowed = {"space_id", "concept_id", "due_before", "status", "paused"}
    if set(filters) - allowed:
        raise AppError(422, "invalid_filter", "不支持的复习筛选条件")
    if "due_before" in filters:
        filters["due_before"] = timestamp(_aware_filter(filters["due_before"]))
    context = page_context(actor.owner_id, "reviews", filters)
    position = read_cursor(cursor, context, limit)
    cutoff = (
        _aware_filter(filters["due_before"])
        if "due_before" in filters
        else (position["cutoff"] if position else datetime.now(UTC))
    )
    where = ["r.owner_id=%s", "r.is_current=1", "s.status='active'", "r.due_at<=%s"]
    args = [actor.owner_id, sql_time(cutoff)]
    for field in ("space_id", "concept_id", "status"):
        if field in filters:
            where.append(f"r.{field}=%s")
            args.append(filters[field])
    where.append("r.paused=%s")
    args.append(bool(filters.get("paused", False)))
    if position:
        where.append("(r.due_at>%s OR (r.due_at=%s AND r.review_task_id>%s))")
        args.extend(
            (sql_time(position["time"]), sql_time(position["time"]), position["id"])
        )
    rows = await fetch_all(
        "SELECT r.* FROM review_tasks r JOIN learning_spaces s ON s.space_id=r.space_id AND s.owner_id=r.owner_id WHERE "
        + " AND ".join(where)
        + " ORDER BY r.due_at,r.review_task_id LIMIT %s",
        (*args, limit + 1),
    )
    page = list(rows[:limit])
    return {
        "items": [await authorized_review_view(actor.owner_id, row) for row in page],
        "next_cursor": write_cursor(
            context, page[-1]["due_at"], page[-1]["review_task_id"], cutoff=cutoff
        )
        if len(rows) > limit
        else None,
    }


async def _append_event(
    conn,
    row,
    event_type,
    *,
    previous_due_at,
    actor_id=None,
    task_id=None,
    key=None,
    request_hash=None,
    payload=None,
):
    await execute(
        "INSERT INTO review_task_events(event_id,review_task_id,owner_id,actor_id,event_type,revision,task_id,origin_kind,origin_id,previous_due_at,due_at,idempotency_key,request_hash,payload_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            uid("review_event"),
            row["review_task_id"],
            row["owner_id"],
            actor_id,
            event_type,
            row["revision"],
            task_id,
            row["origin_kind"],
            row["origin_id"],
            previous_due_at,
            row["due_at"],
            key,
            request_hash,
            dump(payload or {}),
        ),
        conn=conn,
    )


async def update_review(actor, review_id, body):
    body = ReviewUpdateBody.model_validate(body)
    async with transaction() as conn:
        batch = await authorize_review_batch(
            conn, actor.owner_id, [review_id], require_active=body.action != "pause"
        )
        row = batch.reviews[0]
        if row["revision"] != body.expected_revision:
            raise conflict("review_revision_conflict", "复习安排已更新，请刷新后重试")
        if row["is_current"] != 1 or row["status"] == "completed":
            raise conflict("review_not_current", "此复习安排已结束，请刷新后重试")
        changed = {**row, "revision": row["revision"] + 1}
        if body.action == "reschedule":
            changed["override_due_at"] = changed["due_at"] = sql_time(body.due_at)
        else:
            changed["paused"] = body.action == "pause"
        await execute(
            "UPDATE review_tasks SET paused=%s,override_due_at=%s,due_at=%s,revision=%s,updated_at=UTC_TIMESTAMP(6) WHERE review_task_id=%s AND owner_id=%s",
            (
                changed["paused"],
                changed["override_due_at"],
                changed["due_at"],
                changed["revision"],
                review_id,
                actor.owner_id,
            ),
            conn=conn,
        )
        await execute(
            "UPDATE learner_concept_state SET paused=%s,override_due_at=%s,due_at=%s,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE owner_id=%s AND space_id=%s AND concept_id=%s AND scope_revision=%s",
            (
                changed["paused"],
                changed["override_due_at"],
                changed["due_at"],
                actor.owner_id,
                row["space_id"],
                row["concept_id"],
                row["scope_revision"],
            ),
            conn=conn,
        )
        await _append_event(
            conn,
            changed,
            body.action,
            previous_due_at=row["due_at"],
            actor_id=actor.owner_id,
            payload={"bound_task_id": row["task_id"]},
        )
        return review_view(changed, space=batch.space, concept=batch.concepts[0])


async def claim_review_occurrences(
    conn,
    owner_id,
    *,
    review_task_ids,
    expected_revisions,
    task_id,
    origin_kind,
    origin_id,
    key,
    request_hash,
    scope,
    provenance_revisions=(),
):
    """Bind one user-requested job atomically; shared by quiz and practice.

    The caller's transaction must include job insertion and (for practice) its
    activity root. Replay returns the saved binding; a different key cannot win
    a currently claimed occurrence. Explicit terminal retries append history.
    """
    _require_transaction(conn)
    request = ReviewQuizBody(
        review_task_ids=review_task_ids, expected_revisions=expected_revisions
    )
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise AppError(422, "idempotency_required", "需要有效 Idempotency-Key")
    task = await fetch_one(
        "SELECT * FROM quiz_tasks WHERE task_id=%s AND user_id=%s FOR UPDATE",
        (task_id, owner_id),
        conn=conn,
    )
    expected_job = {
        "quiz": ("quiz", "quiz.generate"),
        "practice": ("practice_generate", "practice.generate"),
    }.get(origin_kind)
    if (
        task is None
        or expected_job is None
        or (task["kind"], task["operation"]) != expected_job
        or task["mode"] != "production"
    ):
        raise not_found()
    if task["idempotency_key"] != key or task["request_hash"] != request_hash:
        raise conflict("idempotency_conflict", "相同操作标识已用于不同请求")
    actual_origin = (
        task["quiz_id"]
        if origin_kind == "quiz"
        else load(task["request_json"], {}).get("practice_id")
    )
    if actual_origin != origin_id or ResolvedScope.model_validate(
        load(task["scope_json"])
    ) != ResolvedScope.model_validate(scope):
        raise conflict("review_binding_conflict", "复习任务与固定活动身份不一致")
    batch = await authorize_review_batch(
        conn,
        owner_id,
        request.review_task_ids,
        require_active=task["status"] in {"pending", "running"},
        scope=scope,
        provenance_revisions=provenance_revisions,
        practice_id=origin_id if origin_kind == "practice" else None,
    )
    old_events = []
    for row in batch.reviews:
        event = await fetch_one(
            "SELECT * FROM review_task_events WHERE owner_id=%s AND review_task_id=%s AND idempotency_key=%s FOR SHARE",
            (owner_id, row["review_task_id"], key),
            conn=conn,
        )
        if event and (
            event["request_hash"] != request_hash or event["task_id"] != task_id
        ):
            raise conflict("idempotency_conflict", "相同操作标识已用于不同请求")
        old_events.append(event)
    if all(old_events):
        for row in batch.reviews:
            if (
                row["task_id"] == task_id
                and row["origin_kind"] == origin_kind
                and row["origin_id"] == origin_id
            ):
                if row["paused"] and task["status"] in {"pending", "running"}:
                    raise conflict("review_paused", "复习已暂停，请先恢复")
                continue
            # An earlier terminal attempt remains replayable as history, but
            # can never authorize generation against a newer binding.
            if task["status"] not in {"failed", "cancelled"}:
                raise conflict("review_binding_conflict", "复习已绑定另一个活动")
        return batch
    if any(old_events):
        raise conflict("review_binding_conflict", "复习批次认领记录不完整")
    if task["status"] != "pending" or task["cancel_requested"]:
        raise conflict("review_task_terminal", "请显式重试并使用新的操作标识")
    for row in batch.reviews:
        if row["is_current"] != 1 or row["status"] == "completed":
            raise conflict("review_not_current", "此复习安排已结束，请刷新后重试")
        if row["paused"]:
            raise conflict("review_paused", "复习已暂停，请先恢复")
        if row["status"] in {"claimed", "running"}:
            raise conflict("review_already_claimed", "该复习已开始，请继续已有练习")
        if row["revision"] != request.expected_revisions[row["review_task_id"]]:
            raise conflict("review_revision_conflict", "复习安排已更新，请刷新后重试")
    changed_rows = []
    claimed_at = sql_time(datetime.now(UTC))
    for row in batch.reviews:
        changed = {
            **row,
            "revision": row["revision"] + 1,
            "status": "claimed",
            "task_id": task_id,
            "origin_kind": origin_kind,
            "origin_id": origin_id,
            "claimed_at": claimed_at,
            "last_error_code": None,
        }
        await execute(
            "UPDATE review_tasks SET status='claimed',task_id=%s,origin_kind=%s,origin_id=%s,claimed_at=%s,last_error_code=NULL,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE review_task_id=%s AND owner_id=%s",
            (
                task_id,
                origin_kind,
                origin_id,
                claimed_at,
                row["review_task_id"],
                owner_id,
            ),
            conn=conn,
        )
        await _append_event(
            conn,
            changed,
            "retry" if row["status"] in {"failed", "cancelled"} else "claim",
            previous_due_at=row["due_at"],
            actor_id=owner_id,
            task_id=task_id,
            key=key,
            request_hash=request_hash,
            payload={
                "expected_revision": row["revision"],
                "scope_fingerprint": batch.scope.fingerprint,
                "previous_task_id": row["task_id"],
            },
        )
        changed_rows.append(changed)
    return ReviewBatch(batch.space, batch.scope, batch.concepts, tuple(changed_rows))


def review_request_hash(body):
    body = ReviewQuizBody.model_validate(body)
    request = body.model_dump(mode="json")
    request["review_task_ids"] = sorted(request["review_task_ids"])
    return digest(dump({"entrypoint": "study.review_quiz", "request": request}))


async def authorize_review_binding(
    conn,
    owner_id,
    *,
    review_task_ids,
    expected_revisions,
    task_id,
    origin_kind,
    origin_id,
    scope,
    request_hash,
    provenance_revisions=(),
    require_active=True,
    lock_concepts=True,
):
    """Reauthorize a saved shared claim before execution, publication or replay.

    The caller locks any existing activity root before source/concept work.
    The generation request supplies the original metadata scope revisions.
    """
    _require_transaction(conn)
    task = await fetch_one(
        "SELECT * FROM quiz_tasks WHERE task_id=%s AND user_id=%s FOR UPDATE",
        (task_id, owner_id),
        conn=conn,
    )
    expected_job = {
        "quiz": ("quiz", "quiz.generate"),
        "practice": ("practice_generate", "practice.generate"),
    }.get(origin_kind)
    if (
        task is None
        or expected_job is None
        or (task["kind"], task["operation"]) != expected_job
        or task["mode"] != "production"
        or task["request_hash"] != request_hash
    ):
        raise not_found()
    saved_id = (
        task["quiz_id"]
        if origin_kind == "quiz"
        else load(task["request_json"], {}).get("practice_id")
    )
    if (
        saved_id != origin_id
        or ResolvedScope.model_validate(load(task["scope_json"])) != scope
    ):
        raise conflict("review_binding_conflict", "复习任务与固定活动身份不一致")
    active_task = task["status"] in {"pending", "running"}
    if active_task and task["cancel_requested"]:
        raise conflict("review_task_cancelled", "复习生成已取消")
    batch = await authorize_review_batch(
        conn,
        owner_id,
        review_task_ids,
        require_active=require_active or active_task,
        scope=scope,
        provenance_revisions=provenance_revisions,
        lock_reviews=False,
        lock_concepts=lock_concepts,
        practice_id=origin_id if origin_kind == "practice" else None,
    )
    # Current reads reject a pause/claim that committed after an older RR
    # snapshot. Every dependency is already authorized; the space root keeps
    # publication's following binding checks within the same dependency set.
    current_rows = await _review_rows(owner_id, review_task_ids, conn=conn, lock=True)
    if set(expected_revisions) != set(review_task_ids):
        raise conflict("review_binding_conflict", "复习版本记录不完整")
    for row in current_rows:
        saved_claim = await fetch_one(
            "SELECT * FROM review_task_events WHERE owner_id=%s AND review_task_id=%s AND task_id=%s AND event_type IN ('claim','retry') AND request_hash=%s AND idempotency_key=%s FOR SHARE",
            (
                owner_id,
                row["review_task_id"],
                task_id,
                request_hash,
                task["idempotency_key"],
            ),
            conn=conn,
        )
        if (
            saved_claim is None
            or load(saved_claim["payload_json"], {}).get("expected_revision")
            != expected_revisions[row["review_task_id"]]
            or saved_claim["origin_kind"] != origin_kind
            or saved_claim["origin_id"] != origin_id
        ):
            raise conflict("review_binding_conflict", "复习任务未绑定此来源活动")
        bound = (row["task_id"], row["origin_kind"], row["origin_id"]) == (
            task_id,
            origin_kind,
            origin_id,
        )
        if active_task and (
            not bound
            or row["is_current"] != 1
            or row["status"] not in {"claimed", "running"}
        ):
            raise conflict("review_binding_conflict", "复习任务已由其他活动替代")
        if active_task and row["paused"]:
            raise conflict("review_paused", "复习已暂停，请先恢复")
        if not bound and task["status"] not in {"failed", "cancelled"}:
            raise conflict("review_binding_conflict", "复习任务已由其他活动替代")
    return ReviewBatch(batch.space, batch.scope, batch.concepts, tuple(current_rows))


async def authorize_review_quiz_context(
    owner_id,
    spec,
    scope,
    context,
    *,
    conn=None,
    require_active=True,
    lock_concepts=True,
):
    from app.services import job_service, learning_quiz_service
    from app.services.quiz_service import parse_quiz_request

    if conn is None:
        async with transaction() as tx:
            return await authorize_review_quiz_context(
                owner_id,
                spec,
                scope,
                context,
                conn=tx,
                require_active=require_active,
                lock_concepts=lock_concepts,
            )
    origin = context.origin
    task = job_service.decode(
        await fetch_one(
            "SELECT * FROM quiz_tasks WHERE task_id=%s AND user_id=%s FOR UPDATE",
            (origin.task_id, owner_id),
            conn=conn,
        )
    )
    if task is None or not task["request"]:
        raise AppError(404, "source_revoked", "关联资料已删除或授权已变更")
    saved_spec, saved_context = parse_quiz_request(task["request"])
    if (
        saved_spec != spec
        or saved_context != context
        or task["quiz_id"] != origin.quiz_id
    ):
        raise conflict("learning_request_changed", "练习请求与已保存的学习上下文不一致")
    batch = await authorize_review_binding(
        conn,
        owner_id,
        review_task_ids=origin.review_task_ids,
        expected_revisions=origin.expected_revisions,
        task_id=origin.task_id,
        origin_kind="quiz",
        origin_id=origin.quiz_id,
        scope=scope,
        request_hash=learning_quiz_service.learning_request_hash(spec, context),
        provenance_revisions=(
            origin.space_title_scope_revision,
            *origin.concept_scope_revisions.values(),
        ),
        require_active=require_active,
        lock_concepts=lock_concepts,
    )
    if (
        context.unit_id is not None
        or context.space_id != batch.space["space_id"]
        or context.scope_revision != batch.reviews[0]["scope_revision"]
        or set(batch.concept_ids)
        != {objective.concept_id for objective in context.objectives}
    ):
        raise conflict("review_binding_conflict", "复习概念与已保存的任务不一致")
    return batch


async def start_review_quiz(actor, body, key):
    from app.learning.contracts import ObjectiveRef
    from app.learning.coverage import build_learning_coverage
    from app.rag.contracts import QuizSpec
    from app.services import job_service, learning_quiz_service, quiz_service

    body = ReviewQuizBody.model_validate(body)
    if not isinstance(key, str) or not key.strip() or len(key) > 128:
        raise AppError(422, "idempotency_required", "需要有效 Idempotency-Key")
    request_hash = review_request_hash(body)
    replay = await job_service.existing_job(actor.owner_id, "quiz", key, request_hash)
    if replay:
        await learning_quiz_service.authorize_job(
            actor.owner_id, replay, require_active=False
        )
        return await job_service.get_task(actor.owner_id, replay["task_id"])
    batch = await preview_review_batch(actor.owner_id, body.review_task_ids)
    objectives = [
        ObjectiveRef(concept_id=row["concept_id"], title=row["title"])
        for row in batch.concepts
    ]
    spec, scope, request = quiz_service.resolved_quiz_request(
        actor,
        QuizSpec(
            user_input="；".join(objective.title for objective in objectives),
            objective_titles=[objective.title for objective in objectives],
            question_count=body.question_count,
            difficulty=body.difficulty,
            source_policy="strict_docs",
            scope=learning_quiz_service.requested_scope(batch.scope),
        ),
        batch.scope,
    )
    plan, mapping = build_learning_coverage(spec, scope, objectives)
    # The queue owns task/quiz ID allocation. Its uncommitted construction row
    # receives a strict complete context before the same transaction can commit.
    construction_id = uid("review_request")
    request["review_construction_id"] = construction_id
    async with transaction() as conn:
        task = await job_service.enqueue_job(
            actor.owner_id,
            "quiz",
            request,
            key,
            scope=scope.model_dump(mode="json"),
            request_hash=request_hash,
            conn=conn,
        )
        task = await job_service.existing_job(
            actor.owner_id, "quiz", key, request_hash, conn=conn, lock=True
        )
        if task["request"].get("review_construction_id") == construction_id:
            context = learning_quiz_service.LearningQuizContext(
                space_id=batch.space["space_id"],
                scope_revision=batch.reviews[0]["scope_revision"],
                objectives=objectives,
                coverage_plan=plan,
                target_concepts=mapping,
                origin=learning_quiz_service.ReviewQuizOrigin(
                    review_task_ids=sorted(body.review_task_ids),
                    expected_revisions=body.expected_revisions,
                    task_id=task["task_id"],
                    quiz_id=task["quiz_id"],
                    concept_scope_revisions={
                        row["concept_id"]: row["scope_revision"]
                        for row in batch.concepts
                    },
                    space_title_scope_revision=batch.space["title_scope_revision"],
                ),
            )
            request.pop("review_construction_id")
            request["learning_context"] = context.model_dump(mode="json")
            await execute(
                "UPDATE quiz_tasks SET request_json=%s WHERE task_id=%s AND user_id=%s",
                (dump(request), task["task_id"], actor.owner_id),
                conn=conn,
            )
            task["request"] = request
            await claim_review_occurrences(
                conn,
                actor.owner_id,
                review_task_ids=body.review_task_ids,
                expected_revisions=body.expected_revisions,
                task_id=task["task_id"],
                origin_kind="quiz",
                origin_id=task["quiz_id"],
                key=key,
                request_hash=request_hash,
                scope=scope,
                provenance_revisions=(
                    context.origin.space_title_scope_revision,
                    *context.origin.concept_scope_revisions.values(),
                ),
            )
        else:
            await learning_quiz_service.authorize_job(
                actor.owner_id, task, conn=conn, require_active=False
            )
    return await job_service.get_task(actor.owner_id, task["task_id"])


async def reconcile_review_generation(conn, job):
    """Keep a failed/cancelled binding and append body-free retry history.

    Called only with the actual task locked by owner reconciliation. Source
    revocation cannot prevent recording a terminal status; no text is read.
    """
    _require_transaction(conn)
    if job["status"] not in {"failed", "cancelled"}:
        return
    rows = await fetch_all(
        "SELECT * FROM review_tasks WHERE owner_id=%s AND task_id=%s AND status IN ('claimed','running') ORDER BY space_id,concept_id,review_task_id",
        (job["user_id"], job["task_id"]),
        conn=conn,
    )
    for space_id in sorted({row["space_id"] for row in rows}):
        await scopes.owned_space(job["user_id"], space_id, conn=conn, lock=True)
    for row in rows:
        await fetch_one(
            "SELECT revision FROM learner_concept_state WHERE owner_id=%s AND space_id=%s AND concept_id=%s AND scope_revision=%s FOR UPDATE",
            (job["user_id"], row["space_id"], row["concept_id"], row["scope_revision"]),
            conn=conn,
        )
    for preview in sorted(rows, key=lambda row: row["review_task_id"]):
        row = await fetch_one(
            "SELECT * FROM review_tasks WHERE review_task_id=%s AND owner_id=%s FOR UPDATE",
            (preview["review_task_id"], job["user_id"]),
            conn=conn,
        )
        if row["task_id"] != job["task_id"] or row["status"] not in {
            "claimed",
            "running",
        }:
            continue
        code = job["error_code"] or job["status"]
        changed = {
            **row,
            "revision": row["revision"] + 1,
            "status": job["status"],
            "last_error_code": code,
        }
        await execute(
            "UPDATE review_tasks SET status=%s,last_error_code=%s,revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE review_task_id=%s AND owner_id=%s",
            (job["status"], code, row["review_task_id"], job["user_id"]),
            conn=conn,
        )
        await _append_event(
            conn,
            changed,
            job["status"],
            previous_due_at=row["due_at"],
            task_id=job["task_id"],
            payload={"error_code": code},
        )
