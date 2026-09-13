"""Learning effect and model cost observation (E02).

只读聚合：从体验事件、结算事实与 provider 计量读取，可解释的分母，
无样本返回 null。不创建题目、不调用模型、不修改评分或复习安排。
"""

from datetime import datetime

from app.core.db import fetch_all, fetch_one


def observed_rate(successes: int, eligible: int) -> float | None:
    if not isinstance(successes, int) or not isinstance(eligible, int):
        raise ValueError("invalid_sample_counts")
    if eligible < 0 or not 0 <= successes <= eligible:
        raise ValueError("invalid_sample_counts")
    return None if eligible == 0 else successes / eligible


def metric(numerator, denominator, *, sample_count=None, unknown_count=0, detail=None):
    rate = None
    if isinstance(numerator, int) and isinstance(denominator, int):
        rate = observed_rate(numerator, denominator)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": rate,
        "sample_count": sample_count if sample_count is not None else denominator,
        "unknown_count": unknown_count,
        **({"detail": detail} if detail else {}),
    }


async def _first_lesson_completion(owner: int, start_utc: datetime, end_utc: datetime) -> dict:
    """首课完成：窗口内创建成功课程中，首课有已保存检查的课程占比。"""
    row = await fetch_one(
        "SELECT COUNT(*) AS n FROM learning_courses WHERE owner_id=%s "
        "AND created_at>=%s AND created_at<%s AND status IN ('ready','partial')",
        (owner, start_utc, end_utc),
    )
    observable = row["n"] if row else 0
    done = await fetch_one(
        "SELECT COUNT(DISTINCT course.course_id) AS n FROM learning_courses course "
        "JOIN learning_course_lessons lesson ON lesson.course_id=course.course_id "
        "AND lesson.owner_id=course.owner_id AND lesson.position=0 "
        "JOIN learning_course_check_attempts attempt ON attempt.lesson_id=lesson.lesson_id "
        "AND attempt.owner_id=lesson.owner_id AND attempt.revoked_at IS NULL "
        "WHERE course.owner_id=%s AND course.created_at>=%s AND course.created_at<%s",
        (owner, start_utc, end_utc),
    )
    return metric(done["n"] if done else 0, observable,
                  detail="分母不含资料不足或生成失败的课程")


async def _wait_and_recovery(owner: int, start_utc: datetime, end_utc: datetime) -> dict:
    """等待与恢复：首块可见耗时（客户端上报）、重试与流中断计数。"""
    rows = await fetch_all(
        "SELECT name,COUNT(*) AS n,AVG(elapsed_ms) AS avg_ms FROM learning_experience_events "
        "WHERE owner_id=%s AND received_at>=%s AND received_at<%s AND name IN "
        "('content_first_visible','task_retry_clicked','content_stream_interrupted') "
        "GROUP BY name",
        (owner, start_utc, end_utc),
    )
    by_name = {row["name"]: row for row in rows}
    first_visible = by_name.get("content_first_visible")
    return {
        "first_content_visible_avg_ms": int(first_visible["avg_ms"]) if first_visible and first_visible["avg_ms"] is not None else None,
        "first_content_visible_samples": first_visible["n"] if first_visible else 0,
        "task_retries": by_name.get("task_retry_clicked", {}).get("n", 0),
        "stream_interruptions": by_name.get("content_stream_interrupted", {}).get("n", 0),
    }


async def _cost_benefit(owner: int, start_utc: datetime, end_utc: datetime) -> dict:
    """成本观察：按阶段的调用次数与 usage 缺失（unknown）计数；未知费用不是 0。"""
    rows = await fetch_all(
        "SELECT stage,status,COUNT(*) AS n,"
        "SUM(usage_json IS NULL) AS unknown_usage FROM provider_calls "
        "WHERE owner_id=%s AND created_at>=%s AND created_at<%s GROUP BY stage,status",
        (owner, start_utc, end_utc),
    )
    stages = {}
    for row in rows:
        entry = stages.setdefault(row["stage"], {"calls": 0, "unknown_usage": 0})
        entry["calls"] += row["n"]
        entry["unknown_usage"] += row["unknown_usage"] or 0
    return {"stages": stages, "note": "未知 usage 保留为 unknown，不视为免费"}


async def summarize_learning_metrics(owner: int, start_utc: datetime, end_utc: datetime) -> dict:
    """E02 的可观察接口：分母明确的指标 + 体验计数 + 成本观察。

    纠错后表现与延迟表现依赖 B03 确认纠正与复习结算的真实使用数据，
    在无样本时返回 null，不伪造进步。
    """
    return {
        "window": {"start": start_utc.isoformat(), "end": end_utc.isoformat()},
        "first_lesson_completion": await _first_lesson_completion(owner, start_utc, end_utc),
        "wait_and_recovery": await _wait_and_recovery(owner, start_utc, end_utc),
        "post_correction_performance": metric(None, 0, detail="样本不足：等待真实使用数据"),
        "delayed_performance": metric(None, 0, detail="样本不足：等待复习结算积累"),
        "cost_benefit": await _cost_benefit(owner, start_utc, end_utc),
    }
