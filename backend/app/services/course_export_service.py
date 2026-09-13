"""Personal outcome export as Markdown and one printable snapshot (C01).

导出的主体是本人已保存记录：自检回答、客观题结算、应用回答与确认纠正。
未提交题目的标准答案、rubric、待发布评分提示不进入导出。
"""

import html
import re

from app.core.db import fetch_all
from app.core.errors import AppError
from app.core.values import dump, iso, load
from app.models.course_export import (
    CourseExportCitation,
    CourseExportRecord,
    CourseExportSnapshot,
    CourseExportView,
)

MAX_RECORDS = 200


def markdown_label(value: str) -> str:
    escaped = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|])", r"\\\1", escaped)


def literal_answer_block(value: str) -> str:
    # 字面块同时做 HTML 转义：缩进保持字面形态，内容不成为可执行标签。
    escaped = html.escape(value, quote=False)
    return "\n".join("    " + line for line in escaped.splitlines())


def export_filename(course_id: str) -> str:
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", course_id)[:64]
    return "xunke-learning-" + safe_id + ".md"


def _confirmation_label(value: str) -> str:
    return {
        "not_applicable": "",
        "provisional": "（暂定反馈）",
        "confirmed": "（已确认）",
    }[value]


def _build_markdown(snapshot: CourseExportSnapshot) -> str:
    lines = [
        f"# {markdown_label(snapshot.title)} · 学习成果",
        "",
        f"- 导出时间：{snapshot.generated_at}",
        f"- 目标版本：criteria_revision {snapshot.criteria_revision}",
        f"- 范围：当前内容版本（不含历史版本正文）" if not snapshot.include_history
        else "- 范围：包含历史版本",
        "",
        "## 我的学习摘要",
        *[f"- {markdown_label(item)}" for item in snapshot.personal_summary],
        "",
        "## 目标与证据",
    ]
    for outcome in snapshot.outcomes.criteria or []:
        lines.append(
            f"- {markdown_label(outcome.title)}："
            f"{outcome.status} —— {markdown_label(outcome.reason)}"
        )
    lines += ["", "## 我的回答与纠正"]
    for record in snapshot.records:
        lines.append(f"### {markdown_label(record.title)}")
        lines.append(f"- 时间：{record.occurred_at}" +
                     (f" · 内容版本 v{record.content_version}" if record.content_version else ""))
        if record.help_usage_label:
            lines.append(f"- 帮助使用：{markdown_label(record.help_usage_label)}")
        if record.own_answer:
            lines.append("", )
            lines.append(literal_answer_block(record.own_answer))
        if record.feedback_text:
            lines.append(f"- 反馈{_confirmation_label(record.confirmation)}："
                         f"{markdown_label(record.feedback_text)}")
        lines.append("")
    if snapshot.sources:
        lines += ["## 资料引用"]
        lines += [f"- [{markdown_label(item.export_ref)}] {markdown_label(item.title)}"
                  + (f" · {markdown_label(item.locator)}" if item.locator else "")
                  for item in snapshot.sources]
    if snapshot.warnings:
        lines += ["", "> " + " ".join(markdown_label(w) for w in snapshot.warnings)]
    return "\n".join(lines)


async def build_course_export(owner: int, course_id: str, *, include_history: bool = False) -> CourseExportView:
    from app.services import course_outcome_service, course_read

    if include_history:
        raise AppError(422, "export_scope_unavailable", "历史版本导出尚未开放，请使用当前版本")
    course = await course_read.owned_course(owner, course_id)
    await course_read.authorize_course(course)
    spec = load(course["spec_json"], {})
    outcomes = await course_outcome_service.get_course_outcomes(owner, course_id)
    lessons = await fetch_all(
        "SELECT lesson_id,unit_json,content_version FROM learning_course_lessons "
        "WHERE owner_id=%s AND course_id=%s AND content_json IS NOT NULL",
        (owner, course_id),
    )
    lesson_titles = {
        row["lesson_id"]: load(row["unit_json"], {}).get("title") or "课时"
        for row in lessons
    }
    records: list[CourseExportRecord] = []
    for row in await fetch_all(
        "SELECT attempt_id,lesson_id,content_version,check_ref,answer_json,saved_at,revoked_at "
        "FROM learning_course_check_attempts WHERE owner_id=%s AND course_id=%s "
        "AND revoked_at IS NULL ORDER BY saved_at LIMIT %s",
        (owner, course_id, MAX_RECORDS),
    ):
        answer = load(row["answer_json"], {}).get("answer", "")
        records.append(CourseExportRecord(
            kind="self_check",
            title=f"自检 · {lesson_titles.get(row['lesson_id'], '课时')}",
            occurred_at=row["saved_at"].isoformat(),
            content_version=row["content_version"],
            own_answer=answer if isinstance(answer, str) else "、".join(answer),
        ))
    for row in await fetch_all(
        "SELECT quiz.quiz_id,quiz.settled_at,link.lesson_id FROM quiz_sessions quiz "
        "JOIN quiz_tasks task ON task.task_id=quiz.origin_task_id AND task.user_id=quiz.user_id "
        "JOIN learning_course_quiz_links link ON link.task_id=task.task_id AND link.owner_id=task.user_id "
        "WHERE quiz.user_id=%s AND link.course_id=%s AND quiz.settled_at IS NOT NULL "
        "ORDER BY quiz.settled_at LIMIT %s",
        (owner, course_id, 50),
    ):
        records.append(CourseExportRecord(
            kind="quiz_result",
            title=f"客观检查 · {lesson_titles.get(row['lesson_id'], '课时')}",
            occurred_at=row["settled_at"].isoformat(),
            feedback_text="已完成结算；正确率与逐题解析见课程页，此处不复制题目与答案。",
        ))
    corrections = await fetch_all(
        "SELECT c.correction_id,c.feedback_id,c.body,c.created_at,c.confirmation "
        "FROM learning_course_corrections c JOIN learning_course_feedback f "
        "ON f.feedback_id=c.feedback_id AND f.owner_id=c.owner_id "
        "WHERE c.owner_id=%s AND f.course_id=%s AND c.confirmation='confirmed' "
        "ORDER BY c.created_at LIMIT 50",
        (owner, course_id),
    )
    for row in corrections:
        records.append(CourseExportRecord(
            kind="correction",
            title="已确认纠正",
            occurred_at=row["created_at"].isoformat(),
            own_answer=row["body"],
            confirmation="confirmed",
        ))
    if len(records) >= MAX_RECORDS:
        raise AppError(422, "export_scope_too_large", "学习记录过多，请先缩小范围再导出")
    verified = sum(1 for item in outcomes.criteria or [] if item.status == "verified")
    total = len(outcomes.criteria or [])
    checks_saved = sum(1 for record in records if record.kind == "self_check")
    snapshot = CourseExportSnapshot(
        course_id=course_id,
        title=spec.get("topic") or "我的课程",
        generated_at=iso(__import__("app.core.values", fromlist=["now"]).now()),
        criteria_revision=outcomes.criteria_revision,
        include_history=include_history,
        outcomes=outcomes,
        personal_summary=[
            f"已保存 {checks_saved} 次自检",
            f"目标状态：已验证 {verified} 项 / 共 {total} 项",
        ],
        records=records,
        sources=[
            CourseExportCitation(export_ref=f"S{number}", title=source.get("title", "资料"),
                                 document_version_id=source.get("document_version_id"),
                                 locator=source.get("locator"))
            for number, source in enumerate(
                (load(course["outline_json"], {}).get("sources") or [])[:50], start=1)
        ],
        warnings=["导出仅含当前内容版本；待验证目标不代表已掌握。"],
    )
    return CourseExportView(
        filename=export_filename(course_id),
        generated_at=snapshot.generated_at,
        snapshot=snapshot,
        markdown=_build_markdown(snapshot),
    )
