"""Transactional study spaces, editable goals and immutable chapter selections."""

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load, uid
from app.models.sources import PublicResolvedScope
from app.models.study import StudySpaceCreate, StudySpaceView
from app.services import learning_scope_service as scopes
from app.services import qa_practice_source, source_service

REVOKED_SPACE_TITLE = "资料已失效的学习空间"
REVOKED_GOAL_TITLE = "资料已失效的学习目标"
REVOKED_UNIT_TITLE = "资料已失效的学习单元"


def space_request_hash(body) -> str:
    body = StudySpaceCreate.model_validate(body)
    request = body.model_dump(mode="json")
    if request["scope"]:
        documents = request["scope"]["documents"]
        for document in documents:
            document["section_ids"] = sorted(document["section_ids"])
        documents.sort(key=lambda document: document["doc_id"])
    return digest(dump(request))


def _expected(row, expected_revision):
    if row["revision"] != expected_revision:
        raise conflict("revision_conflict", "内容已更新，请刷新后重试")


async def space_view(row, *, conn=None) -> StudySpaceView:
    if row["active_scope_revision"] is None or row["title_scope_revision"] is None:
        raise not_found()
    scope = await scopes.stored_scope(
        row["owner_id"], row["space_id"], row["active_scope_revision"], conn=conn
    )
    available = await scopes.scope_available(scope, conn=conn)
    title_available = available
    if row["title_scope_revision"] != row["active_scope_revision"]:
        title_scope = await scopes.stored_scope(
            row["owner_id"], row["space_id"], row["title_scope_revision"], conn=conn
        )
        title_available = await scopes.scope_available(title_scope, conn=conn)
    return StudySpaceView(
        space_id=row["space_id"],
        title=row["title"] if title_available else REVOKED_SPACE_TITLE,
        timezone=row["timezone"],
        status=row["status"],
        scope_revision=row["active_scope_revision"],
        revision=row["revision"],
        scope=PublicResolvedScope.from_scope(scope) if available else None,
        source_status="active" if available else "revoked",
        created_at=iso(row["created_at"]),
        updated_at=iso(row["updated_at"]),
    )


async def get_space(owner_id, space_id):
    async with transaction() as conn:
        return await space_view(
            await scopes.owned_space(owner_id, space_id, conn=conn), conn=conn
        )


async def list_spaces(owner_id, page=1, page_size=20, status=None):
    condition, arguments = "owner_id=%s", [owner_id]
    if status is not None:
        condition += " AND status=%s"
        arguments.append(status)
    async with transaction() as conn:
        count = await fetch_one(
            "SELECT COUNT(*) AS n FROM learning_spaces WHERE " + condition,
            arguments,
            conn=conn,
        )
        rows = await fetch_all(
            "SELECT * FROM learning_spaces WHERE "
            + condition
            + " ORDER BY updated_at DESC,space_id DESC LIMIT %s OFFSET %s",
            [*arguments, page_size, (page - 1) * page_size],
            conn=conn,
        )
        return {
            "items": [await space_view(row, conn=conn) for row in rows],
            "total": count["n"],
            "page": page,
            "page_size": page_size,
        }


async def get_scope(owner_id, space_id, scope_revision):
    async with transaction() as conn:
        scope = await scopes.read_scope(owner_id, space_id, scope_revision, conn=conn)
        return {
            "space_id": space_id,
            "scope_revision": scope_revision,
            "scope": PublicResolvedScope.from_scope(scope),
        }


async def create_space(actor, body, key) -> StudySpaceView:
    body = StudySpaceCreate.model_validate(body)
    if not isinstance(key, str) or not 1 <= len(key) <= 128 or not key.strip():
        raise AppError(422, "idempotency_required", "需要有效的创建操作标识")
    request_hash = space_request_hash(body)
    old = await fetch_one(
        "SELECT space_id FROM learning_spaces WHERE owner_id=%s AND idempotency_key=%s",
        (actor.owner_id, key),
    )
    resolved = None
    if old is None:
        if body.answer_id:
            _, resolved, _ = await qa_practice_source.load_answer(
                actor.owner_id, body.answer_id
            )
        else:
            resolved = await source_service.resolve_scope(actor, body.scope)
    candidate_id = uid("space")
    async with transaction() as conn:
        # The unique operation key serializes concurrent creates on the space
        # root itself. An exclusive user lock would invert the order of source
        # revocation and its task/user foreign-key check.
        await execute(
            "INSERT INTO learning_spaces(space_id,owner_id,title,timezone,idempotency_key,request_hash) "
            "VALUES(%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE space_id=space_id",
            (
                candidate_id,
                actor.owner_id,
                body.title,
                body.timezone,
                key,
                request_hash,
            ),
            conn=conn,
        )
        saved = await fetch_one(
            "SELECT * FROM learning_spaces WHERE owner_id=%s AND idempotency_key=%s FOR UPDATE",
            (actor.owner_id, key),
            conn=conn,
        )
        if saved is None:
            raise not_found()
        if saved["space_id"] != candidate_id:
            if saved["request_hash"] != request_hash:
                raise conflict("idempotency_conflict", "此操作标识已用于不同的创建请求")
            # A replay authorizes the original source even when the space's
            # active scope has since changed to an unrelated, available one.
            await scopes.read_scope(actor.owner_id, saved["space_id"], 1, conn=conn)
            result = await space_view(saved, conn=conn)
        else:
            if resolved is None:
                raise not_found()
            space_id = candidate_id
            await scopes.save_scope(conn, actor.owner_id, space_id, 1, resolved)
            await execute(
                "UPDATE learning_spaces SET active_scope_revision=1,title_scope_revision=1 "
                "WHERE space_id=%s AND owner_id=%s",
                (space_id, actor.owner_id),
                conn=conn,
            )
            result = await space_view(
                await scopes.owned_space(actor.owner_id, space_id, conn=conn), conn=conn
            )
    return result


async def update_space(actor, space_id, body) -> StudySpaceView:
    async with transaction() as conn:
        row = await scopes.owned_space(actor.owner_id, space_id, conn=conn, lock=True)
        _expected(row, body.expected_revision)
        updates, values = [], []
        if body.title is not None:
            await scopes.read_scope(
                actor.owner_id, space_id, row["active_scope_revision"], conn=conn
            )
            updates.extend(["title=%s", "title_scope_revision=%s"])
            values.extend([body.title, row["active_scope_revision"]])
        for field in ("timezone", "status"):
            value = getattr(body, field)
            if value is not None:
                updates.append(field + "=%s")
                values.append(value)
        if updates:
            await execute(
                "UPDATE learning_spaces SET "
                + ",".join(updates)
                + ",revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE space_id=%s AND owner_id=%s",
                [*values, space_id, actor.owner_id],
                conn=conn,
            )
        return await space_view(
            await scopes.owned_space(actor.owner_id, space_id, conn=conn), conn=conn
        )


async def change_scope(actor, space_id, body) -> StudySpaceView:
    await scopes.owned_space(actor.owner_id, space_id)
    resolved = await source_service.resolve_scope(actor, body.scope)
    async with transaction() as conn:
        row = await scopes.owned_space(actor.owner_id, space_id, conn=conn, lock=True)
        _expected(row, body.expected_revision)
        revision = row["active_scope_revision"] + 1
        await scopes.save_scope(conn, actor.owner_id, space_id, revision, resolved)
        # The title retains its old provenance until an explicit authorized
        # rename; switching sources alone cannot reveal old revoked text.
        await execute(
            "UPDATE learning_spaces SET active_scope_revision=%s,revision=revision+1,updated_at=UTC_TIMESTAMP(6) "
            "WHERE space_id=%s AND owner_id=%s",
            (revision, space_id, actor.owner_id),
            conn=conn,
        )
        return await space_view(
            await scopes.owned_space(actor.owner_id, space_id, conn=conn), conn=conn
        )


async def owned_goal(owner_id, goal_id, *, conn=None, lock=False):
    if lock and conn is None:
        raise ValueError("A goal lock requires an existing transaction")
    row = await fetch_one(
        "SELECT * FROM learning_goals WHERE goal_id=%s AND owner_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (goal_id, owner_id),
        conn=conn,
    )
    if row is None:
        raise not_found()
    return row


async def owned_unit(owner_id, unit_id, *, conn=None, lock=False):
    if lock and conn is None:
        raise ValueError("A unit lock requires an existing transaction")
    row = await fetch_one(
        "SELECT * FROM learning_units WHERE unit_id=%s AND owner_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (unit_id, owner_id),
        conn=conn,
    )
    if row is None:
        raise not_found()
    return row


async def goal_view(row, *, conn=None):
    scope = await scopes.stored_scope(
        row["owner_id"], row["space_id"], row["scope_revision"], conn=conn
    )
    available = await scopes.scope_available(scope, conn=conn)
    return {
        "goal_id": row["goal_id"],
        "space_id": row["space_id"],
        "scope_revision": row["scope_revision"],
        "title": row["title"] if available else REVOKED_GOAL_TITLE,
        "deadline": row["deadline"],
        "daily_minutes": row["daily_minutes"],
        "status": row["status"],
        "revision": row["revision"],
        "source_status": "active" if available else "revoked",
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
    }


async def unit_view(row, *, conn=None):
    scope = await scopes.stored_scope(
        row["owner_id"], row["space_id"], row["scope_revision"], conn=conn
    )
    available = await scopes.scope_available(scope, conn=conn)
    return {
        "unit_id": row["unit_id"],
        "goal_id": row["goal_id"],
        "space_id": row["space_id"],
        "scope_revision": row["scope_revision"],
        "title": row["title"] if available else REVOKED_UNIT_TITLE,
        "scope": load(row["section_selection_json"]) if available else None,
        "position": row["position"],
        "status": row["status"],
        "revision": row["revision"],
        "source_status": "active" if available else "revoked",
        "created_at": iso(row["created_at"]),
        "updated_at": iso(row["updated_at"]),
    }


async def list_goals(owner_id, space_id):
    async with transaction() as conn:
        await scopes.owned_space(owner_id, space_id, conn=conn)
        rows = await fetch_all(
            "SELECT * FROM learning_goals WHERE space_id=%s AND owner_id=%s ORDER BY created_at,goal_id",
            (space_id, owner_id),
            conn=conn,
        )
        return {"items": [await goal_view(row, conn=conn) for row in rows]}


async def list_units(owner_id, goal_id):
    async with transaction() as conn:
        goal = await owned_goal(owner_id, goal_id, conn=conn)
        await scopes.owned_space(owner_id, goal["space_id"], conn=conn)
        rows = await fetch_all(
            "SELECT * FROM learning_units WHERE goal_id=%s AND owner_id=%s ORDER BY position,unit_id",
            (goal_id, owner_id),
            conn=conn,
        )
        return {
            "items": [await unit_view(row, conn=conn) for row in rows],
            "goal_revision": goal["revision"],
        }


async def create_goal(actor, space_id, body):
    async with transaction() as conn:
        space = await scopes.owned_space(actor.owner_id, space_id, conn=conn, lock=True)
        scopes.require_active(space)
        revision = body.scope_revision or space["active_scope_revision"]
        await scopes.read_scope(actor.owner_id, space_id, revision, conn=conn)
        goal_id = uid("goal")
        await execute(
            "INSERT INTO learning_goals(goal_id,owner_id,space_id,scope_revision,title,deadline,daily_minutes,status) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                goal_id,
                actor.owner_id,
                space_id,
                revision,
                body.title,
                body.deadline,
                body.daily_minutes,
                body.status,
            ),
            conn=conn,
        )
        return await goal_view(
            await owned_goal(actor.owner_id, goal_id, conn=conn), conn=conn
        )


async def update_goal(actor, goal_id, body):
    preview = await owned_goal(actor.owner_id, goal_id)
    async with transaction() as conn:
        await scopes.owned_space(
            actor.owner_id, preview["space_id"], conn=conn, lock=True
        )
        row = await owned_goal(actor.owner_id, goal_id, conn=conn, lock=True)
        _expected(row, body.expected_revision)
        await scopes.read_scope(
            actor.owner_id, row["space_id"], row["scope_revision"], conn=conn
        )
        updates, values = [], []
        for field in ("title", "deadline", "daily_minutes", "status"):
            value = getattr(body, field)
            if (
                value is not None
                or field == "deadline"
                and field in body.model_fields_set
            ):
                updates.append(field + "=%s")
                values.append(value)
        if updates:
            await execute(
                "UPDATE learning_goals SET "
                + ",".join(updates)
                + ",revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE goal_id=%s AND owner_id=%s",
                [*values, goal_id, actor.owner_id],
                conn=conn,
            )
        return await goal_view(
            await owned_goal(actor.owner_id, goal_id, conn=conn), conn=conn
        )


async def _touch_goal(conn, owner_id, goal_id):
    await execute(
        "UPDATE learning_goals SET revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE goal_id=%s AND owner_id=%s",
        (goal_id, owner_id),
        conn=conn,
    )


async def _write_positions(conn, owner_id, goal_id, rows, positions):
    if not rows:
        return
    offset = max(row["position"] for row in rows) + len(rows) + 1
    # Move all rows above the occupied range before assigning final nonnegative
    # positions, preserving the unique (goal_id, position) constraint throughout.
    await execute(
        "UPDATE learning_units SET position=position+%s WHERE goal_id=%s AND owner_id=%s",
        (offset, goal_id, owner_id),
        conn=conn,
    )
    for row in rows:
        await execute(
            "UPDATE learning_units SET position=%s,revision=revision+1,updated_at=UTC_TIMESTAMP(6) "
            "WHERE unit_id=%s AND owner_id=%s",
            (positions[row["unit_id"]], row["unit_id"], owner_id),
            conn=conn,
        )


async def create_unit(actor, goal_id, body):
    preview = await owned_goal(actor.owner_id, goal_id)
    async with transaction() as conn:
        space = await scopes.owned_space(
            actor.owner_id, preview["space_id"], conn=conn, lock=True
        )
        scopes.require_active(space)
        goal = await owned_goal(actor.owner_id, goal_id, conn=conn, lock=True)
        await scopes.read_scope(
            actor.owner_id, space["space_id"], goal["scope_revision"], conn=conn
        )
        scope = await scopes.read_scope(
            actor.owner_id, space["space_id"], body.scope_revision, conn=conn
        )
        selection = scopes.checked_unit_selection(scope, body.scope)
        rows = await fetch_all(
            "SELECT * FROM learning_units WHERE goal_id=%s AND owner_id=%s ORDER BY position,unit_id",
            (goal_id, actor.owner_id),
            conn=conn,
        )
        if len(rows) >= 100:
            raise conflict("study_unit_limit", "每个学习目标最多保存 100 个单元")
        if body.position > len(rows):
            raise AppError(422, "invalid_unit_position", "单元位置超出当前目标的范围")
        unit_id = uid("unit")
        ordered = [row["unit_id"] for row in rows]
        ordered.insert(body.position, unit_id)
        await _write_positions(
            conn,
            actor.owner_id,
            goal_id,
            rows,
            {value: index for index, value in enumerate(ordered)},
        )
        await execute(
            "INSERT INTO learning_units(unit_id,goal_id,owner_id,space_id,scope_revision,title,section_selection_json,position,status) "
            "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                unit_id,
                goal_id,
                actor.owner_id,
                space["space_id"],
                body.scope_revision,
                body.title,
                dump(selection),
                body.position,
                body.status,
            ),
            conn=conn,
        )
        await _touch_goal(conn, actor.owner_id, goal_id)
        return await unit_view(
            await owned_unit(actor.owner_id, unit_id, conn=conn), conn=conn
        )


async def update_unit(actor, unit_id, body):
    preview = await owned_unit(actor.owner_id, unit_id)
    async with transaction() as conn:
        await scopes.owned_space(
            actor.owner_id, preview["space_id"], conn=conn, lock=True
        )
        await owned_goal(actor.owner_id, preview["goal_id"], conn=conn, lock=True)
        row = await owned_unit(actor.owner_id, unit_id, conn=conn, lock=True)
        _expected(row, body.expected_revision)
        await scopes.read_scope(
            actor.owner_id, row["space_id"], row["scope_revision"], conn=conn
        )
        updates, values = [], []
        for field in ("title", "status"):
            value = getattr(body, field)
            if value is not None:
                updates.append(field + "=%s")
                values.append(value)
        if updates:
            await execute(
                "UPDATE learning_units SET "
                + ",".join(updates)
                + ",revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE unit_id=%s AND owner_id=%s",
                [*values, unit_id, actor.owner_id],
                conn=conn,
            )
            await _touch_goal(conn, actor.owner_id, row["goal_id"])
        return await unit_view(
            await owned_unit(actor.owner_id, unit_id, conn=conn), conn=conn
        )


async def reorder_units(actor, goal_id, body):
    preview = await owned_goal(actor.owner_id, goal_id)
    async with transaction() as conn:
        await scopes.owned_space(
            actor.owner_id, preview["space_id"], conn=conn, lock=True
        )
        goal = await owned_goal(actor.owner_id, goal_id, conn=conn, lock=True)
        _expected(goal, body.expected_revision)
        await scopes.read_scope(
            actor.owner_id, goal["space_id"], goal["scope_revision"], conn=conn
        )
        rows = await fetch_all(
            "SELECT * FROM learning_units WHERE goal_id=%s AND owner_id=%s ORDER BY position,unit_id",
            (goal_id, actor.owner_id),
            conn=conn,
        )
        if len(body.unit_ids) != len(rows) or set(body.unit_ids) != {
            row["unit_id"] for row in rows
        }:
            raise conflict("study_unit_set_changed", "请按当前目标的完整单元列表排序")
        for revision in sorted({row["scope_revision"] for row in rows}):
            await scopes.read_scope(
                actor.owner_id, goal["space_id"], revision, conn=conn
            )
        await _write_positions(
            conn,
            actor.owner_id,
            goal_id,
            rows,
            {value: index for index, value in enumerate(body.unit_ids)},
        )
        await _touch_goal(conn, actor.owner_id, goal_id)
        ordered = await fetch_all(
            "SELECT * FROM learning_units WHERE goal_id=%s AND owner_id=%s ORDER BY position,unit_id",
            (goal_id, actor.owner_id),
            conn=conn,
        )
        return {
            "items": [await unit_view(row, conn=conn) for row in ordered],
            "goal_revision": goal["revision"] + 1,
        }
