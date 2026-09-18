"""Owner-scoped, idempotent, rate-limited diagnostics with no learning side effects."""

from datetime import timedelta

from app.core.config import get_settings
from app.core.db import execute, fetch_one, transaction
from app.core.errors import conflict, not_found, rate_limited
from app.core.values import digest, dump, iso, load, now
from app.models.experience import ExperienceEventInput
from app.services import course_read, rate_limit_service


async def _authorize(owner: int, body: ExperienceEventInput, *, conn):
    course_id = body.course_id
    if body.lesson_id:
        lesson = await fetch_one(
            "SELECT course_id FROM learning_course_lessons WHERE lesson_id=%s AND owner_id=%s",
            (body.lesson_id, owner), conn=conn,
        )
        if not lesson or (course_id and course_id != lesson["course_id"]):
            raise not_found()
        course_id = lesson["course_id"]
    if course_id:
        course = await course_read.owned_course(owner, course_id, conn=conn)
        await course_read.authorize_course(course, conn=conn)
    if body.task_id:
        task = await fetch_one(
            "SELECT kind,request_json FROM quiz_tasks WHERE task_id=%s AND user_id=%s AND mode='production'",
            (body.task_id, owner), conn=conn,
        )
        if not task:
            raise not_found()
        # Use the business readers, including current source authorization.
        from app.services.task_event_stream import _reader_for

        category = {
            "course_outline": "course", "course_lesson": "course", "course_tutor": "course",
            "qa": "qa", "quiz": "quiz", "practice_generate": "practice", "practice_grade": "practice",
            "course_application_generate": "course_application",
            "course_application_feedback": "course_application",
        }.get(task["kind"])
        if category is None:
            raise not_found()
        await _reader_for(category).authorize(owner, body.task_id)
        request = load(task["request_json"], {})
        if course_id and request.get("course_id") != course_id:
            raise not_found()
        if body.lesson_id and request.get("lesson_id") != body.lesson_id:
            raise not_found()


async def record_experience_event(actor, body: ExperienceEventInput) -> dict:
    if not get_settings().experience_events_enabled:
        return {"event_id": body.event_id, "accepted": False, "received_at": None}
    owner = actor.owner_id
    body_hash = digest(dump(body.model_dump(mode="json")))
    async with transaction() as conn:
        # Serializes the small per-owner SQL fallback even when Redis is absent.
        user = await fetch_one("SELECT id FROM users WHERE id=%s FOR UPDATE", (owner,), conn=conn)
        if not user:
            raise not_found()
        existing = await fetch_one(
            "SELECT body_hash,received_at FROM learning_experience_events WHERE owner_id=%s AND event_id=%s",
            (owner, body.event_id), conn=conn,
        )
        await _authorize(owner, body, conn=conn)
        if existing:
            if existing["body_hash"] != body_hash:
                raise conflict("idempotency_conflict", "事件编号已用于其他内容")
            return {"event_id": body.event_id, "accepted": True, "received_at": iso(existing["received_at"])}
        await rate_limit_service.enforce_burst(
            str(owner), "owner:" + str(owner),
            policy=rate_limit_service.BurstPolicy("experience", 60, 60, 60),
        )
        received_at = now()
        count = await fetch_one(
            "SELECT COUNT(*) AS n FROM learning_experience_events WHERE owner_id=%s AND received_at>%s",
            (owner, received_at - timedelta(seconds=60)), conn=conn,
        )
        if count["n"] >= 60:
            raise rate_limited(60)
        await execute(
            "INSERT INTO learning_experience_events(owner_id,event_id,name,course_id,lesson_id,task_id,"
            "elapsed_ms,helpful,body_hash,received_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (owner, body.event_id, body.name, body.course_id, body.lesson_id, body.task_id,
             body.elapsed_ms, body.helpful, body_hash, received_at), conn=conn,
        )
    return {"event_id": body.event_id, "accepted": True, "received_at": iso(received_at)}


async def purge_experience_events(*, owner_id=None, dry_run=False) -> int:
    """Thirty-day retention, independent of model and learning records."""
    clause = "received_at<%s"
    args = [now() - timedelta(days=30)]
    if owner_id is not None:
        clause += " AND owner_id=%s"
        args.append(owner_id)
    if dry_run:
        return (await fetch_one("SELECT COUNT(*) AS n FROM learning_experience_events WHERE " + clause, args))["n"]
    return await execute("DELETE FROM learning_experience_events WHERE " + clause, args)
