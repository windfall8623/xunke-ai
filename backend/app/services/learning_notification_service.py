"""Reminder preferences, in-app reminders and bounded outbox delivery (B07).

默认站内与邮件都关闭；邮件只发给已验证账号，内容只有短提示与站内入口，
不携带答题正文、资料摘录或薄弱点列表。outbox 的身份是
owner+规则版本+计划时间+channel：重放不重复投递，unknown 不自动无限重发。
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter, ValidationError

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load, now, uid
from app.learning.contracts import IanaTimezone
from app.models.learning_notification import (
    LearningReminderList,
    LearningReminderPreferences,
    LearningReminderPreferencesUpdate,
    LearningReminderUpdate,
    LearningReminderView,
)

RULE_VERSION = "learning-reminders-v1"


def may_send_reminder(*, enabled, paused_until, now_utc, already_delivered, source_available):
    return (
        enabled
        and (paused_until is None or paused_until <= now_utc)
        and not already_delivered
        and source_available
    )


def _default_preferences() -> LearningReminderPreferences:
    return LearningReminderPreferences(revision=1)


async def get_preferences(owner: int) -> LearningReminderPreferences:
    row = await fetch_one(
        "SELECT * FROM learning_reminder_preferences WHERE owner_id=%s", (owner,)
    )
    if row is None:
        return _default_preferences()
    return LearningReminderPreferences(
        revision=row["revision"],
        in_app_enabled=row["in_app_enabled"],
        email_enabled=row["email_enabled"],
        frequency=row["frequency"],
        local_time=row["local_time"],
        timezone=row["timezone"],
        paused_until=iso(row["paused_until"]) if row["paused_until"] else None,
    )


async def update_preferences(owner: int, body: LearningReminderPreferencesUpdate):
    paused_until = None
    if body.paused_until:
        try:
            paused_until = datetime.fromisoformat(body.paused_until.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AppError(422, "invalid_pause", "暂停时间无效") from exc
    async with transaction() as conn:
        row = await fetch_one(
            "SELECT * FROM learning_reminder_preferences WHERE owner_id=%s FOR UPDATE",
            (owner,), conn=conn,
        )
        if row is None:
            if body.expected_revision != 1:
                raise conflict("revision_conflict", "提醒设置已更新，请刷新后重试")
            await execute(
                "INSERT INTO learning_reminder_preferences(owner_id,in_app_enabled,"
                "email_enabled,frequency,local_time,timezone,paused_until,revision) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,2)",
                (owner, body.in_app_enabled, body.email_enabled, body.frequency,
                 body.local_time, body.timezone, paused_until),
                conn=conn,
            )
            revision = 2
        else:
            if row["revision"] != body.expected_revision:
                raise conflict("revision_conflict", "提醒设置已更新，请刷新后重试")
            await execute(
                "UPDATE learning_reminder_preferences SET in_app_enabled=%s,email_enabled=%s,"
                "frequency=%s,local_time=%s,timezone=%s,paused_until=%s,revision=revision+1 "
                "WHERE owner_id=%s",
                (body.in_app_enabled, body.email_enabled, body.frequency, body.local_time,
                 body.timezone, paused_until, owner),
                conn=conn,
            )
            revision = row["revision"] + 1
    return LearningReminderPreferences(
        revision=revision,
        in_app_enabled=body.in_app_enabled,
        email_enabled=body.email_enabled,
        frequency=body.frequency,
        local_time=body.local_time,
        timezone=body.timezone,
        paused_until=body.paused_until,
    )


def _view(row) -> LearningReminderView:
    return LearningReminderView(
        reminder_id=row["reminder_id"], kind=row["kind"], title=row["title"],
        body=row["body"], link_path=row["link_path"],
        due_at=iso(row["due_at"]) if row["due_at"] else None,
        read_at=iso(row["read_at"]) if row["read_at"] else None,
        created_at=row["created_at"].isoformat(),
    )


async def list_reminders(owner: int, *, limit: int = 20) -> LearningReminderList:
    rows = await fetch_all(
        "SELECT * FROM learning_reminders WHERE owner_id=%s "
        "ORDER BY created_at DESC,reminder_id LIMIT %s",
        (owner, limit),
    )
    return LearningReminderList(items=[_view(row) for row in rows], total=len(rows))


async def update_reminder(owner: int, reminder_id: str, body: LearningReminderUpdate):
    """已读只更新提醒；稍后提醒只改本条的 send_after，不伪造完成。"""
    send_after = None
    if body.action == "snooze":
        if not body.send_after:
            raise AppError(422, "invalid_snooze", "稍后提醒需要指定时间")
        try:
            send_after = datetime.fromisoformat(body.send_after.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AppError(422, "invalid_snooze", "稍后提醒时间无效") from exc
    async with transaction() as conn:
        row = await fetch_one(
            "SELECT * FROM learning_reminders WHERE reminder_id=%s AND owner_id=%s FOR UPDATE",
            (reminder_id, owner), conn=conn,
        )
        if row is None:
            raise not_found()
        if body.action == "read":
            await execute(
                "UPDATE learning_reminders SET read_at=%s WHERE reminder_id=%s AND owner_id=%s",
                (now(), reminder_id, owner), conn=conn,
            )
        else:
            await execute(
                "UPDATE learning_reminders SET send_after=%s WHERE reminder_id=%s AND owner_id=%s",
                (send_after, reminder_id, owner), conn=conn,
            )
        row = await fetch_one(
            "SELECT * FROM learning_reminders WHERE reminder_id=%s AND owner_id=%s",
            (reminder_id, owner), conn=conn,
        )
    return _view(row)


def _identity(owner: int, *, week_start: str, channel: str) -> str:
    return digest(dump([owner, RULE_VERSION, week_start, channel]))[:64]


async def insert_in_app_reminder(owner: int, *, kind, title, body=None, link_path=None, due_at=None):
    reminder_id = uid("rem")
    await execute(
        "INSERT INTO learning_reminders(reminder_id,owner_id,kind,title,body,link_path,due_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s)",
        (reminder_id, owner, kind, title[:200], body[:500] if body else None,
         link_path, due_at),
    )
    return reminder_id


async def enqueue_due_review_reminder(owner: int, *, lesson_title: str, link_path: str, due_at):
    """每日到期提醒：身份含当天，重放不重复；关闭时不入队。"""
    prefs = await get_preferences(owner)
    if not prefs.in_app_enabled and not prefs.email_enabled:
        return None
    week_key = due_at.astimezone(ZoneInfo(str(prefs.timezone))).date().isoformat()
    identity = _identity(owner, week_start=f"daily:{week_key}", channel="in_app")
    known = await fetch_one(
        "SELECT delivery_id FROM learning_reminder_outbox WHERE owner_id=%s AND identity_key=%s "
        "AND channel='in_app'",
        (owner, identity),
    )
    if known:
        return None
    delivery_id = uid("dlv")
    await execute(
        "INSERT INTO learning_reminder_outbox(delivery_id,owner_id,identity_key,channel,"
        "scheduled_for,payload_json) VALUES(%s,%s,%s,'in_app',%s,%s)",
        (delivery_id, owner, identity, due_at,
         dump({"kind": "due_review", "title": f"到期复习 · {lesson_title}", "link_path": link_path})),
    )
    return delivery_id


async def _deliver_outbox_row(row, *, apply: bool) -> str:
    """返回 'sent' 或 'retry'；SMTP 结果未知按可重试处理，不标记成功。"""
    payload = load(row["payload_json"], {})
    if row["channel"] == "in_app":
        if not apply:
            return "sent"
        await insert_in_app_reminder(
            row["owner_id"], kind=payload.get("kind", "course_event"),
            title=payload.get("title", "学习提醒"), body=payload.get("body"),
            link_path=payload.get("link_path"),
        )
        return "sent"
    from app.services import mail_transport

    settings = get_settings()
    identity = await fetch_one(
        "SELECT subject FROM auth_identities WHERE user_id=%s AND provider='password' "
        "AND app_scope='web' AND email_verified_at IS NOT NULL LIMIT 1",
        (row["owner_id"],),
    )
    if not identity or not mail_transport.is_ready(settings):
        return "retry"
    if not apply:
        return "sent"
    try:
        mail_transport.send_learning_reminder_email(
            identity["subject"], payload.get("title", "学习提醒"),
            payload.get("link_path") or "/study",
        )
    except Exception:
        return "retry"
    return "sent"


async def deliver_due_reminders(limit: int = 20, *, apply: bool = True) -> int:
    """小批投递到期 outbox；邮件失败保留可重试，不自动无限重发。"""
    rows = await fetch_all(
        "SELECT * FROM learning_reminder_outbox WHERE status='pending' AND scheduled_for<=%s "
        "ORDER BY scheduled_for LIMIT %s",
        (now(), limit),
    )
    delivered = 0
    for row in rows:
        outcome = await _deliver_outbox_row(row, apply=apply)
        if outcome == "sent":
            await execute(
                "UPDATE learning_reminder_outbox SET status='sent',sent_at=%s "
                "WHERE delivery_id=%s AND owner_id=%s",
                (now(), row["delivery_id"], row["owner_id"]),
            )
            delivered += 1
        else:
            attempts = row["attempts"] + 1
            status = "failed" if attempts >= 5 else "pending"
            await execute(
                "UPDATE learning_reminder_outbox SET attempts=%s,status=%s,"
                "last_error_code=%s WHERE delivery_id=%s AND owner_id=%s",
                (attempts, status, "delivery_unavailable", row["delivery_id"], row["owner_id"]),
            )
    return delivered


async def enqueue_weekly_digests(limit: int = 100, *, apply: bool = True, now_utc=None) -> int:
    """为开启周报的用户建立本周投递身份；默认关闭的用户不会入队。"""
    now_utc = now_utc or datetime.now(UTC)
    rows = await fetch_all(
        "SELECT * FROM learning_reminder_preferences WHERE in_app_enabled=TRUE "
        "OR email_enabled=TRUE LIMIT %s",
        (limit,),
    )
    scheduled = 0
    for row in rows:
        prefs = LearningReminderPreferences(
            revision=row["revision"], in_app_enabled=row["in_app_enabled"],
            email_enabled=row["email_enabled"], frequency=row["frequency"],
            local_time=row["local_time"], timezone=row["timezone"],
            paused_until=iso(row["paused_until"]) if row["paused_until"] else None,
        )
        if prefs.frequency != "weekly":
            continue
        try:
            zone = ZoneInfo(str(TypeAdapter(IanaTimezone).validate_python(prefs.timezone)))
        except (ValidationError, ValueError):
            continue
        local_now = now_utc.astimezone(zone)
        local_send = local_now.replace(
            hour=int(prefs.local_time[:2]), minute=int(prefs.local_time[3:5]),
            second=0, microsecond=0,
        )
        if local_send > local_now:
            continue
        week_start = (local_send - timedelta(days=local_send.weekday())).date().isoformat()
        paused = bool(prefs.paused_until and prefs.paused_until > iso(now_utc))
        for channel, enabled in (("in_app", prefs.in_app_enabled), ("email", prefs.email_enabled)):
            if not enabled or paused:
                continue
            identity = _identity(row["owner_id"], week_start=week_start, channel=channel)
            known = await fetch_one(
                "SELECT delivery_id FROM learning_reminder_outbox "
                "WHERE owner_id=%s AND identity_key=%s AND channel=%s",
                (row["owner_id"], identity, channel),
            )
            if known:
                continue
            scheduled += 1
            if not apply:
                continue
            await execute(
                "INSERT INTO learning_reminder_outbox(delivery_id,owner_id,identity_key,channel,"
                "scheduled_for,payload_json) VALUES(%s,%s,%s,%s,%s,%s)",
                (uid("dlv"), row["owner_id"], identity, channel, now_utc,
                 dump({"kind": "weekly_summary", "title": "本周学习周报已生成",
                       "link_path": "/study"})),
            )
    return scheduled
