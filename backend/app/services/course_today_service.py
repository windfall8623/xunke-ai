"""Read-only daily suggestions, ordered by unfinished work and existing due dates."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter, ValidationError

from app.core.db import fetch_all
from app.core.errors import AppError
from app.core.values import load
from app.learning.contracts import IanaTimezone
from app.models.course_review import CourseTodayItem, CourseTodayView
from app.services import course_progress, course_quiz_service, course_read, course_review_service, review_service


def _activity_tokens(item):
    tokens = {
        f"{field}:{item[field]}"
        for field in ("quiz_id", "task_id", "link_id", "review_id", "review_task_id")
        if item.get(field)
    }
    if item.get("course_id") and item.get("lesson_id"):
        tokens.add(f"lesson:{item['course_id']}:{item['lesson_id']}")
    if not tokens and item.get("course_id"):
        tokens.add(f"course:{item['course_id']}")
    return tokens


def select_today_items(candidates, minutes_budget):
    """Preserve priority, deduplicate activities, then fit at most three items."""
    selected, seen, warnings = [], set(), []
    remaining = minutes_budget
    for candidate in candidates:
        item = CourseTodayItem.model_validate(candidate).model_dump(mode="json")
        tokens = _activity_tokens(item)
        if tokens & seen:
            continue
        seen.update(tokens)
        estimate = item["estimated_minutes"]
        if not selected and estimate > minutes_budget:
            item["reason"] += " 预计用时超过今日预算，可以分次学习。"
            selected.append(item)
            warnings.append("首要活动预计用时超过预算，可分次完成；预计分钟不代表实际学习耗时。")
            break
        if estimate > remaining:
            continue
        selected.append(item)
        remaining -= estimate
        if len(selected) == 3:
            break
    return selected, warnings


def _title(lesson):
    return load(lesson.get("unit_json"), {}).get("title") or "课时"


def _estimate(lesson, kind):
    if kind in {"continue_quiz", "course_review", "practice_lesson", "study_review"}:
        return 5
    value = load(lesson.get("unit_json"), {}).get("estimated_minutes", 10)
    return value if isinstance(value, int) and value > 0 else 10


async def _course_candidates(owner, course, now_utc):
    course_id = course["course_id"]
    await course_read.authorize_course(course)
    lessons = await fetch_all(
        "SELECT * FROM learning_course_lessons WHERE owner_id=%s AND course_id=%s ORDER BY position",
        (owner, course_id),
    )
    if not lessons or course["status"] not in {"ready", "partial"}:
        spec = load(course["spec_json"], {})
        reason = (
            "课程纲要尚未准备完成，进入课程查看状态并重试。"
            if course["status"] in {"failed", "cancelled"}
            else "课程纲要正在准备，进入课程查看进度。"
        )
        return [], [], [{
            "kind": "learn_lesson", "title": (spec.get("topic") or "课程")[:200],
            "estimated_minutes": 5, "reason": reason, "course_id": course_id,
            "task_id": course.get("outline_task_id"),
        }]
    by_lesson = {lesson["lesson_id"]: lesson for lesson in lessons if course_progress._available(lesson)}
    links = await course_quiz_service._link_rows(owner, course_id)
    unfinished = []
    for link in links:
        lesson = by_lesson.get(link["lesson_id"])
        if (
            not lesson or lesson["status"] != "ready"
            or link["content_version"] != lesson["content_version"]
            or not course_review_service._unfinished(link)
        ):
            continue
        unfinished.append({
            "kind": "continue_quiz", "title": f"继续检查 · {_title(lesson)}",
            "estimated_minutes": 5,
            "reason": "本课还有未完成的检查，先继续这次练习。",
            "course_id": course_id, "lesson_id": link["lesson_id"],
            "link_id": link["link_id"], "task_id": link["task_id"], "quiz_id": link["quiz_id"],
        })
    reviews = await course_review_service.list_course_reviews(owner, course_id)
    due, recoveries = [], []
    for review in reviews:
        if review["status"] not in {"scheduled", "generating", "ready", "failed"}:
            continue
        lesson = by_lesson.get(review["lesson_id"])
        if lesson is None:
            continue
        link = next((link for link in links if link["link_id"] == review["active_link_id"]), None)
        item = {
            "kind": "course_review", "title": f"复习 · {_title(lesson)}",
            "estimated_minutes": 5, "reason": review["reason"],
            "course_id": course_id, "lesson_id": review["lesson_id"], "review_id": review["review_id"],
            "link_id": review["active_link_id"], "task_id": link["task_id"] if link else None,
            "quiz_id": link["quiz_id"] if link else None,
        }
        due_at = datetime.fromisoformat(review["due_at"].replace("Z", "+00:00"))
        if due_at <= now_utc:
            if review["status"] == "scheduled":
                item["reason"] = "已到本课建议复习时间，再做三题检查理解。"
            due.append((due_at, item))
        elif review["status"] == "failed":
            item["reason"] = "上次复习出题失败，可进入课程恢复；若未到期，需明确选择提前复习。"
            recoveries.append(item)
    progress = await course_progress.get_progress(owner, course_id)
    action = progress["next_action"]
    next_steps = []
    if action["type"] in {"learn_lesson", "practice_lesson", "review_lesson"}:
        lesson = by_lesson.get(action["lesson_id"])
        if lesson:
            reason = action["reason"]
            if lesson["status"] in {"failed", "cancelled"}:
                reason = "本课内容尚未生成成功，进入课时后可重新生成。"
            next_steps.append({
                "kind": action["type"], "title": _title(lesson),
                "estimated_minutes": _estimate(lesson, action["type"]), "reason": reason,
                "course_id": course_id, "lesson_id": action["lesson_id"],
                "quiz_id": action["quiz_id"], "link_id": action["link_id"],
                "task_id": action["task_id"] or lesson.get("generation_task_id"),
            })
    await course_read.authorize_course(course)
    return unfinished, due, recoveries + next_steps


async def get_today(actor, timezone: str = "Asia/Shanghai", minutes_budget: int = 20, *, now_utc=None):
    try:
        timezone = TypeAdapter(IanaTimezone).validate_python(timezone)
    except (ValidationError, ValueError) as exc:
        raise AppError(422, "invalid_timezone", "请提供有效的 IANA 时区") from exc
    if isinstance(minutes_budget, bool) or not isinstance(minutes_budget, int) or not 5 <= minutes_budget <= 120:
        raise AppError(422, "invalid_minutes_budget", "今日学习预算应为 5–120 分钟")
    now_utc = now_utc or datetime.now(UTC)
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    now_utc = now_utc.astimezone(UTC)
    courses = await fetch_all(
        "SELECT * FROM learning_courses WHERE owner_id=%s AND status<>'source_revoked' "
        "ORDER BY updated_at DESC,course_id DESC",
        (actor.owner_id,),
    )
    unfinished, due, next_steps = [], [], []
    available_courses = 0
    for course in courses:
        try:
            course_unfinished, course_due, course_next = await _course_candidates(actor.owner_id, course, now_utc)
        except AppError as exc:
            if exc.status != 404:
                raise
            continue
        available_courses += 1
        unfinished.extend(course_unfinished)
        due.extend(course_due)
        next_steps.extend(course_next)
    study = await review_service.list_due_reviews(
        actor, filters={"due_before": now_utc.isoformat()}, limit=50,
    )
    for review in study["items"]:
        if (
            review["source_status"] != "active" or review["paused"] or not review["is_current"]
            or review["status"] == "completed"
        ):
            continue
        item = {
            "kind": "study_review", "title": f"复习 · {review['concept_title']}",
            "estimated_minutes": 5,
            "reason": "学习空间中已有到期复习，继续原有复习活动。",
            "space_id": review["space_id"], "review_task_id": review["review_task_id"],
            "task_id": review["task_id"],
            "quiz_id": review["origin_id"] if review["origin_kind"] == "quiz" else None,
        }
        due.append((datetime.fromisoformat(review["due_at"].replace("Z", "+00:00")), item))
    candidates = unfinished + [item for _, item in sorted(due, key=lambda pair: pair[0])] + next_steps
    items, warnings = select_today_items(candidates, minutes_budget)
    if not items:
        warnings.append(
            "当前没有可继续的课程活动或到期复习，可进入课程查看学习记录与资料状态。"
            if available_courses else "暂时没有可继续的学习活动，可以先创建课程或学习空间。"
        )
    return CourseTodayView(
        local_date=now_utc.astimezone(ZoneInfo(timezone)).date().isoformat(),
        timezone=timezone, minutes_budget=minutes_budget, items=items, warnings=warnings,
    ).model_dump(mode="json")
