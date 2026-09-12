"""任务概览读取：为跨页面完成/失败通知提供轻量快照。

只读 quiz_tasks 与 kb_documents 的当前状态，不写公开事件、不触碰
task_event 流水；qa 与 course_tutor 的回答都在各自会话页内呈现，
不进入全局通知。
"""

from app.core.db import fetch_all
from app.core.values import iso, load
from app.models.task_overview import ProcessingDocument, TaskOverviewItem, TaskOverviewView

WINDOW_MINUTES = 15
TASK_LIMIT = 20
DOC_LIMIT = 10
EXCLUDED_KINDS = ("qa", "course_tutor")
PROCESSING_STATUSES = ("processing", "pending", "queued", "running")

_KIND_LABELS = {
    "quiz": "练习",
    "report": "练习报告",
    "ingest": "资料处理",
    "delete": "资料删除",
    "images": "练习配图",
    "eval_sample": "评测样本",
    "learning_project": "学习空间",
    "practice_generate": "练习生成",
    "practice_grade": "讲解评分",
    "course_outline": "课程纲要",
    "course_lesson": "课时内容",
}


def _short_text(value, limit=60):
    text = (value or "").strip().replace("\n", " ")
    return text[:limit] if text else None


def _course_title(row):
    outline = load(row.get("outline_json"), {})
    payload = outline.get("payload") or {}
    return payload.get("title") or _short_text(load(row.get("spec_json"), {}).get("topic"), 80)


async def get_overview(owner: int) -> TaskOverviewView:
    rows = await fetch_all(
        "SELECT task_id,kind,status,stage,error_code,user_input,request_json,quiz_id,created_at,updated_at "
        "FROM quiz_tasks WHERE user_id=%s AND mode='production' AND kind NOT IN (%s,%s) "
        "AND (status IN ('pending','running') OR updated_at >= UTC_TIMESTAMP(6) - INTERVAL %s MINUTE) "
        "ORDER BY updated_at DESC LIMIT %s",
        (owner, *EXCLUDED_KINDS, WINDOW_MINUTES, TASK_LIMIT),
    )

    lesson_ids: list[str] = []
    course_ids: list[str] = []
    doc_ids: list[str] = []
    for row in rows:
        request = load(row["request_json"], {})
        if row["kind"] == "course_lesson" and request.get("lesson_id"):
            lesson_ids.append(request["lesson_id"])
        if row["kind"] in {"course_outline", "course_lesson"} and request.get("course_id"):
            course_ids.append(request["course_id"])
        if row["kind"] in {"ingest", "delete"} and request.get("doc_id"):
            doc_ids.append(request["doc_id"])

    lessons = {}
    if lesson_ids:
        placeholders = ",".join(["%s"] * len(lesson_ids))
        for item in await fetch_all(
            f"SELECT lesson_id,unit_json FROM learning_course_lessons WHERE owner_id=%s AND lesson_id IN ({placeholders})",
            (owner, *lesson_ids),
        ):
            lessons[item["lesson_id"]] = load(item["unit_json"], {})
    courses = {}
    if course_ids:
        placeholders = ",".join(["%s"] * len(course_ids))
        for item in await fetch_all(
            f"SELECT course_id,outline_json,spec_json FROM learning_courses WHERE owner_id=%s AND course_id IN ({placeholders})",
            (owner, *course_ids),
        ):
            courses[item["course_id"]] = item
    documents = {}
    if doc_ids:
        placeholders = ",".join(["%s"] * len(doc_ids))
        for item in await fetch_all(
            f"SELECT doc_id,file_name FROM kb_documents WHERE user_id=%s AND doc_id IN ({placeholders})",
            (owner, *doc_ids),
        ):
            documents[item["doc_id"]] = item

    tasks = []
    for row in rows:
        request = load(row["request_json"], {})
        title = None
        course_title = None
        doc_id = None
        if row["kind"] == "course_outline":
            course_title = _course_title(courses.get(request.get("course_id"), {})) or _short_text(
                (request.get("spec") or {}).get("topic"), 80
            )
            title = course_title
        elif row["kind"] == "course_lesson":
            lesson = lessons.get(request.get("lesson_id"), {})
            title = lesson.get("title") or _KIND_LABELS.get(row["kind"])
            course_title = _course_title(courses.get(request.get("course_id"), {}))
        elif row["kind"] in {"ingest", "delete"}:
            doc_id = request.get("doc_id")
            title = documents.get(doc_id, {}).get("file_name") or _KIND_LABELS.get(row["kind"])
        else:
            title = _short_text(row.get("user_input")) or _KIND_LABELS.get(row["kind"])
        tasks.append(
            TaskOverviewItem(
                task_id=row["task_id"],
                kind=row["kind"],
                status=row["status"],
                stage=row["stage"],
                error_code=row["error_code"],
                title=title,
                course_id=request.get("course_id"),
                course_title=course_title,
                lesson_id=request.get("lesson_id"),
                quiz_id=row["quiz_id"],
                doc_id=doc_id,
                created_at=iso(row["created_at"]),
                updated_at=iso(row["updated_at"]),
            )
        )

    processing = await fetch_all(
        "SELECT doc_id,file_name,status FROM kb_documents WHERE user_id=%s AND purpose='production' "
        f"AND deleted_at IS NULL AND status IN ({','.join(['%s'] * len(PROCESSING_STATUSES))}) "
        "ORDER BY created_at DESC LIMIT %s",
        (owner, *PROCESSING_STATUSES, DOC_LIMIT),
    )
    return TaskOverviewView(
        tasks=tasks,
        documents=[ProcessingDocument(**item) for item in processing],
    )
