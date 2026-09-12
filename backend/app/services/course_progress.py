"""Read-only course progress from actual reading, submitted answers and settlement."""

from app.core.db import fetch_all, transaction
from app.core.values import iso, load
from app.models.course import CourseProgressView
from app.services import course_read
from app.services.course_quiz_service import _link_rows


def _available(lesson):
    unit = load(lesson.get("unit_json"), {})
    return (
        lesson.get("status") not in {"material_gap", "source_revoked"}
        and unit.get("availability", lesson.get("availability")) != "material_gap"
    )


def _settled(link):
    return bool(
        link.get("quiz_id") and link.get("quiz_status") == "settled"
        and link.get("settled_at")
    )


def pending_review_links(lessons: list[dict], quiz_links: list[dict]) -> list[dict]:
    """A settled child replaces the parent's pending errors, never its history."""
    by_lesson = {lesson["lesson_id"]: lesson for lesson in lessons if _available(lesson)}
    links = [
        link for link in quiz_links
        if link["lesson_id"] in by_lesson
        and link.get("content_version") == by_lesson[link["lesson_id"]].get("content_version")
    ]
    reviewed = {
        link["parent_link_id"] for link in links
        if link["kind"] == "review" and _settled(link)
    }
    return [
        link for link in links
        if _settled(link) and link.get("wrong_question_ids")
        and link["link_id"] not in reviewed
    ]


def select_next_action(lessons: list[dict], quiz_links: list[dict]) -> dict:
    """Prioritize unfinished checks, unreviewed errors, then the next lesson."""
    available = sorted(
        (lesson for lesson in lessons if _available(lesson)),
        key=lambda lesson: lesson.get("position", 0),
    )
    by_lesson = {lesson["lesson_id"]: lesson for lesson in available}
    links = [
        link for link in quiz_links
        if link["lesson_id"] in by_lesson
        and link.get("content_version") == by_lesson[link["lesson_id"]].get("content_version")
    ]

    def action(kind, reason, lesson_id=None, link=None):
        return {
            "type": kind, "reason": reason, "lesson_id": lesson_id,
            "link_id": link["link_id"] if link else None,
            "quiz_id": link.get("quiz_id") if link else None,
            "task_id": link["task_id"] if link else None,
        }

    for link in links:
        if link["task_status"] in {"pending", "running"} or (
            link["task_status"] == "completed" and not _settled(link)
        ):
            return action(
                "continue_quiz", "本课还有未完成的检查，先继续这次练习。",
                link["lesson_id"], link,
            )
    for link in pending_review_links(available, links):
        return action(
            "review_lesson", "这次检查还有尚未补练的错题，建议回看本课后再练。",
            link["lesson_id"], link,
        )
    practiced = {
        link["lesson_id"] for link in links
        if link["kind"] == "initial" and _settled(link)
    }
    for lesson in available:
        if lesson.get("read_at") is None:
            return action(
                "learn_lesson", "继续下一个尚未记录已读的课时。", lesson["lesson_id"]
            )
        if lesson["lesson_id"] not in practiced:
            return action(
                "practice_lesson", "本课已记录已读，接着做三题检查。", lesson["lesson_id"]
            )
    return action(
        "view_summary",
        "当前可用课时的阅读与检查已完成，可查看学习记录。"
        if available else "暂无可开始的课时，请查看课程状态与资料缺口。",
    )


async def get_progress(owner, course_id):
    async with transaction() as conn:
        course = await course_read.owned_course(owner, course_id, conn=conn)
        await course_read.authorize_course(course, conn=conn)
        lessons = await fetch_all(
            "SELECT lesson_id,position,status,unit_json,content_json,content_version,read_at "
            "FROM learning_course_lessons WHERE owner_id=%s AND course_id=%s ORDER BY position",
            (owner, course_id), conn=conn,
        )
        links = await _link_rows(owner, course_id, conn=conn)
        answers = await fetch_all(
            "SELECT link.link_id,answer.question_id,answer.is_correct,quiz.questions_json "
            "FROM learning_course_quiz_links link "
            "JOIN quiz_tasks task ON task.task_id=link.task_id AND task.user_id=link.owner_id "
            "AND task.kind='quiz' AND task.mode='production' AND task.status='completed' "
            "JOIN quiz_sessions quiz ON quiz.quiz_id=task.quiz_id AND quiz.user_id=link.owner_id "
            "AND quiz.origin_task_id=task.task_id "
            "JOIN quiz_answers answer ON answer.quiz_id=quiz.quiz_id AND answer.user_id=link.owner_id "
            "WHERE link.owner_id=%s AND link.course_id=%s "
            "ORDER BY link.created_at,link.link_id,answer.created_at,answer.question_id",
            (owner, course_id), conn=conn,
        )
        by_link = {link["link_id"]: link for link in links}
        for link in links:
            link.update(answered=0, correct=0, wrong_question_ids=[])
        weak_points = []
        for answer in answers:
            link = by_link[answer["link_id"]]
            link["answered"] += 1
            link["correct"] += int(bool(answer["is_correct"]))
            if answer["is_correct"]:
                continue
            link["wrong_question_ids"].append(answer["question_id"])
            question = next(
                (item for item in load(answer["questions_json"], [])
                 if item["id"] == answer["question_id"]),
                None,
            )
            if question:
                weak_points.append({
                    "lesson_id": link["lesson_id"], "link_id": link["link_id"],
                    "quiz_id": link["quiz_id"], "question_id": answer["question_id"],
                    "knowledge_point": question.get("knowledge_point") or question["stem"],
                })
        initial = [link for link in links if link["kind"] == "initial"]
        answered = sum(link["answered"] for link in initial)
        correct = sum(link["correct"] for link in initial)
        review_runs = [
            {
                "link_id": link["link_id"], "lesson_id": link["lesson_id"],
                "kind": link["kind"],
                "quiz_id": link["quiz_id"],
                "status": link["quiz_status"] or link["task_status"],
                "answered": link["answered"], "correct": link["correct"],
                "total": link["question_count"] if link["question_count"] is not None else 3,
                "accuracy": link["correct"] / link["answered"] if link["answered"] else None,
                "created_at": iso(link["created_at"]),
            }
            for link in links if link["kind"] in {"review", "scheduled_review"}
        ]
        pending_ids = {link["link_id"] for link in pending_review_links(lessons, links)}
        return CourseProgressView(
            course_id=course_id,
            total_lessons=len(lessons),
            available_lessons=sum(_available(lesson) for lesson in lessons),
            generated_lessons=sum(
                lesson["content_json"] is not None and lesson["content_version"] > 0
                for lesson in lessons
            ),
            read_lessons=sum(lesson["read_at"] is not None for lesson in lessons),
            practiced_lessons=len({link["lesson_id"] for link in initial if _settled(link)}),
            initial_answered=answered,
            initial_correct=correct,
            initial_accuracy=correct / answered if answered else None,
            review_runs=review_runs,
            weak_points=weak_points,
            pending_weak_points=[point for point in weak_points if point["link_id"] in pending_ids],
            next_action=select_next_action(lessons, links),
        ).model_dump(mode="json")


get_course_progress = get_progress
