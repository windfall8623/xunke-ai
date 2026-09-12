"""Authoritative answer and settlement transactions; language models never award XP."""

from datetime import timezone
from decimal import Decimal

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load
from app.learning.contracts import AssessmentDraft, LearningAttemptDraft
from app.models.learning import QuestionView
from app.rag.contracts import stable_hash
from app.services import learning_event_service as learning_events
from app.services import learning_scope_service as learning_scopes
from app.services.job_service import enqueue_job


async def owned_quiz(owner, quiz_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM quiz_sessions WHERE quiz_id=%s AND user_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (quiz_id, owner),
        conn=conn,
    )
    if not row:
        raise not_found()
    return row


async def _locked_quiz_for_write(conn, owner, quiz_id, *, answer=False):
    link = await fetch_one(
        "SELECT space_id FROM learning_quiz_contexts WHERE quiz_id=%s AND owner_id=%s",
        (quiz_id, owner),
        conn=conn,
    )
    if link:
        # Authorize the full activity/space/metadata union before taking any
        # partial source locks. This also locks space before the quiz root.
        origin = await learning_events._locked_origin(conn, owner, "quiz", quiz_id)
        return origin.row, origin
    quiz = await owned_quiz(owner, quiz_id, conn=conn, lock=True)
    if answer:
        await learning_scopes.require_quiz_sources(owner, quiz, conn=conn)
    return quiz, None


async def get_detail(owner, quiz_id, *, conn=None):
    from app.services.course_read import course_context_for_quiz

    row = await owned_quiz(owner, quiz_id, conn=conn)
    available = await learning_scopes.quiz_sources_available(owner, row, conn=conn)
    course_context = None
    if available:
        try:
            course_context = await course_context_for_quiz(owner, quiz_id, conn=conn)
        except AppError as exc:
            if exc.code != "source_revoked":
                raise
            available = False
    answers = (
        await fetch_all(
            "SELECT receipt_json FROM quiz_answers WHERE quiz_id=%s ORDER BY created_at,question_id",
            (quiz_id,),
            conn=conn,
        )
        if available
        else []
    )
    records = [load(a["receipt_json"])["answer_record"] for a in answers]
    questions = load(row["questions_json"], []) if available else []
    if available and not records and row["status"] == "settled":
        legacy = await fetch_one(
            "SELECT records_json FROM answer_records WHERE quiz_id=%s AND user_id=%s",
            (quiz_id, owner),
            conn=conn,
        )
        by_id = {q["id"]: q for q in questions}
        for record in load(legacy["records_json"] if legacy else None, []):
            q = by_id.get(record.get("question_id"), {})
            records.append(
                {
                    **record,
                    "correct_answers": q.get("answer", []),
                    "explanation": q.get("explanation", ""),
                    "citation_refs": [],
                }
            )
    report = await fetch_one(
        "SELECT status FROM reports WHERE quiz_id=%s AND user_id=%s",
        (quiz_id, owner),
        conn=conn,
    )
    scope = load(row["source_scope_json"]) if available else None
    source_status = row["source_status"] if available else "source_revoked"
    if scope:
        # Browser DTOs expose identities and sections, never server storage keys.
        scope = {
            "documents": [
                {
                    k: m[k]
                    for k in (
                        "doc_id",
                        "document_version_id",
                        "index_build_id",
                        "section_ids",
                        "section_catalog_revision",
                        "title",
                    )
                    if k in m
                }
                for m in scope["documents"]
            ]
        }
    return {
        "quiz_id": quiz_id,
        "title": row["title"] if available else "资料已失效的练习",
        "summary": (row["summary"] or "") if available else "",
        "user_input": row["user_input"] if available else "",
        "questions": [QuestionView.model_validate(q).model_dump() for q in questions],
        "answer_records": records,
        "revision": row["revision"],
        "status": row["status"],
        "source_policy": row["source_policy"],
        "source_status": source_status,
        "source_scope": scope,
        "images_status": row["images_status"],
        "report_status": report["status"] if report else "not_requested",
        "created_at": iso(row["created_at"]),
        "course_context": course_context,
    }


async def submit_answer(owner, quiz_id, question_id, body):
    selected = sorted(body.selected_answers)
    if len(set(selected)) != len(selected):
        raise AppError(422, "invalid_options", "选项不能重复")
    request_hash = digest(
        dump({"selected_answers": selected, "duration_ms": body.duration_ms})
    )
    async with transaction() as conn:
        quiz, origin = await _locked_quiz_for_write(conn, owner, quiz_id, answer=True)
        existing = await fetch_one(
            "SELECT * FROM quiz_answers WHERE quiz_id=%s AND question_id=%s",
            (quiz_id, question_id),
            conn=conn,
        )
        if existing:
            if existing["submission_hash"] != request_hash:
                raise conflict(
                    "answer_already_submitted", "此题已提交，回看不会修改成绩"
                )
            return load(existing["receipt_json"])
        if quiz["status"] != "active":
            raise conflict("quiz_already_settled", "本次练习已经结算")
        question = next(
            (q for q in load(quiz["questions_json"]) if q["id"] == question_id), None
        )
        if not question:
            raise not_found()
        allowed = {option["key"] for option in question["options"]}
        if (
            not set(selected) <= allowed
            or question["type"] in ("single", "judge")
            and len(selected) != 1
        ):
            raise AppError(422, "invalid_options", "所选答案不符合题目选项")
        correct = set(selected) == set(question["answer"])
        totals = await fetch_one(
            "SELECT COUNT(*) AS answered,COALESCE(SUM(is_correct),0) AS correct FROM quiz_answers WHERE quiz_id=%s",
            (quiz_id,),
            conn=conn,
        )
        record = {
            "question_id": question_id,
            "selected_answers": selected,
            "is_correct": correct,
            "duration_ms": body.duration_ms,
            "correct_answers": question["answer"],
            "explanation": question["explanation"],
            "citation_refs": question.get("citation_refs", []),
        }
        receipt = {
            "answer_record": record,
            "revision": quiz["revision"] + 1,
            "answered_count": totals["answered"] + 1,
            "correct_count": int(totals["correct"]) + int(correct),
        }
        await execute(
            "INSERT INTO quiz_answers(quiz_id,question_id,user_id,selected_json,is_correct,duration_ms,submission_hash,receipt_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                quiz_id,
                question_id,
                owner,
                dump(selected),
                correct,
                body.duration_ms,
                request_hash,
                dump(receipt),
            ),
            conn=conn,
        )
        await execute(
            "UPDATE quiz_sessions SET revision=revision+1 WHERE quiz_id=%s",
            (quiz_id,),
            conn=conn,
        )
        if origin is not None:
            saved_answer = await fetch_one(
                "SELECT created_at FROM quiz_answers WHERE quiz_id=%s AND question_id=%s",
                (quiz_id, question_id),
                conn=conn,
            )
            question_version = origin.versions[question_id][0]
            attempt = await learning_events.record_attempt(
                conn,
                owner,
                LearningAttemptDraft(
                    origin_kind="quiz",
                    origin_id=quiz_id,
                    question_id=question_id,
                    question_version=question_version,
                    space_id=origin.space["space_id"],
                    scope_revision=origin.scope_revision,
                    answer_kind=question["type"],
                    answer_json={"selected_answers": selected},
                    response_hash=request_hash,
                    duration_ms=body.duration_ms,
                    # This legacy endpoint has no reliable hint provenance.
                    help_usage="unknown",
                    occurred_at=saved_answer["created_at"].replace(tzinfo=timezone.utc),
                ),
            )
            await learning_events.record_assessment(
                conn,
                owner,
                attempt.attempt_id,
                AssessmentDraft(
                    status="graded",
                    score=Decimal(1 if correct else 0),
                    source="deterministic",
                    confirmation="confirmed",
                    grader_version="objective-set-equality-v1",
                    rubric_version="objective-option-set-v1",
                    rubric_hash=stable_hash(
                        {
                            "version": "objective-option-set-v1",
                            "question_version": question_version,
                            "correct_answers": sorted(question["answer"]),
                        }
                    ),
                    feedback=question["explanation"],
                    evidence_refs=question.get("citation_refs", []),
                    independent_eligible=False,
                ),
            )
        return receipt


async def complete_quiz(owner, quiz_id, expected_revision):
    async with transaction() as conn:
        quiz, origin = await _locked_quiz_for_write(conn, owner, quiz_id)
        if quiz["settled_at"] is not None:
            if quiz["completion_json"]:
                return load(quiz["completion_json"])
            old = await fetch_one(
                "SELECT * FROM answer_records WHERE quiz_id=%s AND user_id=%s",
                (quiz_id, owner),
                conn=conn,
            )
            return {
                "quiz_id": quiz_id,
                "revision": quiz["revision"],
                "xp_awarded": quiz["xp_awarded"],
                "correct_count": old["correct_count"] if old else 0,
                "total_questions": old["total_questions"]
                if old
                else len(load(quiz["questions_json"])),
                "total": old["total_questions"]
                if old
                else len(load(quiz["questions_json"])),
                "accuracy": float(old["accuracy"]) if old else 0,
                "report_status": "completed",
            }
        if quiz["revision"] != expected_revision:
            raise conflict()
        rows = await fetch_all(
            "SELECT receipt_json FROM quiz_answers WHERE quiz_id=%s",
            (quiz_id,),
            conn=conn,
        )
        answers = [load(r["receipt_json"])["answer_record"] for r in rows]
        questions = load(quiz["questions_json"])
        if {a["question_id"] for a in answers} != {q["id"] for q in questions}:
            raise conflict("quiz_incomplete", "请先完成所有题目")
        total = len(questions)
        correct = sum(a["is_correct"] for a in answers)
        accuracy = round(correct / total * 100, 2)
        xp = 10 + 2 * correct
        receipt = {
            "quiz_id": quiz_id,
            "revision": quiz["revision"] + 1,
            "xp_awarded": xp,
            "correct_count": correct,
            "total_questions": total,
            "total": total,
            "accuracy": accuracy,
            "report_status": "pending",
        }
        await execute(
            "INSERT INTO answer_records(quiz_id,user_id,records_json,total_questions,correct_count,accuracy) VALUES(%s,%s,%s,%s,%s,%s)",
            (quiz_id, owner, dump(answers), total, correct, accuracy),
            conn=conn,
        )
        await execute(
            "INSERT INTO reports(quiz_id,user_id,report_json,status,stats_revision) VALUES(%s,%s,NULL,'pending',%s)",
            (quiz_id, owner, receipt["revision"]),
            conn=conn,
        )
        await execute(
            "UPDATE quiz_sessions SET status='settled',settled_at=UTC_TIMESTAMP(6),xp_awarded=%s,revision=revision+1,completion_json=%s WHERE quiz_id=%s",
            (xp, dump(receipt), quiz_id),
            conn=conn,
        )
        await execute(
            "UPDATE users SET total_xp=total_xp+%s WHERE id=%s", (xp, owner), conn=conn
        )
        await enqueue_job(
            owner,
            "report",
            {"quiz_id": quiz_id, "stats_revision": receipt["revision"]},
            f"report:{quiz_id}:initial",
            conn=conn,
        )
        from app.services.course_review_service import append_settlement_event

        # Course quizzes have no legacy learning_context. The outbox belongs to
        # this same successful settlement transaction regardless of that origin.
        await append_settlement_event(conn, owner, quiz_id)
        if origin is not None:
            settled = await fetch_one(
                "SELECT settled_at FROM quiz_sessions WHERE quiz_id=%s AND user_id=%s",
                (quiz_id, owner),
                conn=conn,
            )
            attempts = await fetch_all(
                "SELECT attempt_id FROM learning_attempts WHERE owner_id=%s "
                "AND origin_kind='quiz' AND origin_id=%s ORDER BY question_id",
                (owner, quiz_id),
                conn=conn,
            )
            await learning_events.record_completion(
                conn,
                owner,
                origin_kind="quiz",
                origin_id=quiz_id,
                attempt_ids=[item["attempt_id"] for item in attempts],
                completed_at=settled["settled_at"],
            )
        return receipt


async def get_report(owner, quiz_id):
    quiz = await owned_quiz(owner, quiz_id)
    available = await learning_scopes.quiz_sources_available(owner, quiz)
    row = await fetch_one(
        "SELECT * FROM reports WHERE quiz_id=%s AND user_id=%s", (quiz_id, owner)
    )
    scores = await fetch_one(
        "SELECT * FROM answer_records WHERE quiz_id=%s AND user_id=%s", (quiz_id, owner)
    )
    return {
        "quiz_id": quiz_id,
        "total_questions": scores["total_questions"]
        if scores
        else len(load(quiz["questions_json"])),
        "correct_count": scores["correct_count"] if scores else 0,
        "accuracy": float(scores["accuracy"]) if scores else 0,
        "xp_awarded": quiz["xp_awarded"],
        "report_status": row["status"] if row else "not_requested",
        "report": load(row["report_json"]) if available and row else None,
        "error_code": (row["error_code"] if row else None)
        if available
        else "source_revoked",
        "weak_question_ids": [
            a["question_id"]
            for a in load(scores["records_json"] if scores else None, [])
            if not a["is_correct"]
        ],
    }


async def retry_report(owner, quiz_id, key):
    async with transaction() as conn:
        quiz = await owned_quiz(owner, quiz_id, conn=conn, lock=True)
        if not quiz["settled_at"]:
            raise conflict("quiz_incomplete", "本次练习尚未完成")
        report = await fetch_one(
            "SELECT * FROM reports WHERE quiz_id=%s AND user_id=%s FOR UPDATE",
            (quiz_id, owner),
            conn=conn,
        )
        if report and report["status"] in ("completed", "pending", "running"):
            return {"quiz_id": quiz_id, "report_status": report["status"]}
        await enqueue_job(
            owner,
            "report",
            {"quiz_id": quiz_id, "stats_revision": quiz["revision"]},
            key,
            conn=conn,
        )
        await execute(
            "UPDATE reports SET status='pending',error_code=NULL WHERE quiz_id=%s",
            (quiz_id,),
            conn=conn,
        )
        return {"quiz_id": quiz_id, "report_status": "pending"}


async def history(owner, page, page_size):
    items = await fetch_all(
        """SELECT q.quiz_id,q.title,q.revision,q.status,q.source_status,q.source_scope_json,q.images_status,q.created_at,
          JSON_LENGTH(q.questions_json) AS question_count,a.accuracy,
          (SELECT COUNT(*) FROM quiz_answers x WHERE x.quiz_id=q.quiz_id) AS answered_count,
          COALESCE(r.status,'not_requested') AS report_status
          FROM quiz_sessions q LEFT JOIN answer_records a ON a.quiz_id=q.quiz_id
          LEFT JOIN reports r ON r.quiz_id=q.quiz_id WHERE q.user_id=%s ORDER BY q.created_at DESC,q.id DESC LIMIT %s OFFSET %s""",
        (owner, page_size, (page - 1) * page_size),
    )
    total = await fetch_one(
        "SELECT COUNT(*) AS n FROM quiz_sessions WHERE user_id=%s", (owner,)
    )
    for item in items:
        if not await learning_scopes.quiz_sources_available(owner, item):
            item["title"] = "资料已失效的练习"
            item["source_status"] = "source_revoked"
        item.pop("source_scope_json", None)
        item["accuracy"] = (
            float(item["accuracy"]) if item["accuracy"] is not None else None
        )
        item["created_at"] = iso(item["created_at"])
    return {"items": items, "total": total["n"], "page": page, "page_size": page_size}
