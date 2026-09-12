"""Owner-isolated wrong attempts, activity history and actual concept progress."""

from __future__ import annotations

from decimal import Decimal

from pydantic import TypeAdapter

from app.core.db import fetch_all, fetch_one, transaction
from app.core.errors import AppError, not_found
from app.core.values import load
from app.learning.contracts import AssessmentDraft
from app.learning.review_rules import RULE_VERSION
from app.models.learning import QuestionView
from app.models.practice import public_assessment, public_question
from app.models.sources import PublicResolvedScope
from app.practice.contracts import PracticeQuestion
from app.rag.contracts import ResolvedScope, stable_hash
from app.services import learning_concept_service as concepts
from app.services import learning_event_service as events
from app.services import learning_projection_service as projections
from app.services import learning_scope_service as scopes
from app.services import learning_service
from app.services import review_service as reviews


_PRACTICE_QUESTION = TypeAdapter(PracticeQuestion)
_HEAD_JOIN = (
    " JOIN learning_assessment_heads h ON h.attempt_id=t.attempt_id AND h.owner_id=t.owner_id "
    "JOIN assessment_records a ON a.assessment_id=h.assessment_id AND a.attempt_id=h.attempt_id "
    "AND a.owner_id=h.owner_id AND a.revision=h.revision "
)
_NOT_FULL = "a.score<>'1' AND NOT REGEXP_LIKE(a.score,'^1[.]0+$','c')"
_ZERO = "REGEXP_LIKE(a.score,'^0([.]0+)?$','c')"


def _filters(filters, allowed):
    value = {key: item for key, item in dict(filters or {}).items() if item is not None}
    if set(value) - allowed:
        raise AppError(422, "invalid_filter", "不支持的学习记录筛选条件")
    return value


def _result_status(head):
    if head is None:
        return "pending"
    if head["status"] != "graded":
        return head["status"]
    if head["confirmation"] != "confirmed":
        return "needs_review"
    score = Decimal(head["score"])
    return "correct" if score == 1 else "wrong" if score == 0 else "partial"


def _assessment_view(row):
    draft = AssessmentDraft(
        **{
            field: row[field]
            for field in AssessmentDraft.model_fields
            if field not in {"feedback", "evidence_refs", "criterion_results"}
        },
        feedback=row["feedback"] or "",
        evidence_refs=load(row["evidence_refs_json"], []),
        criterion_results=load(row["criterion_results_json"], []),
    )
    return public_assessment(
        draft,
        assessment_id=row["assessment_id"],
        attempt_id=row["attempt_id"],
        revision=row["revision"],
        created_at=reviews.utc(row["created_at"]),
    ).model_dump(mode="json")


def _public_question(origin, attempt):
    question = origin.questions[attempt["question_id"]]
    if origin.kind == "quiz":
        return QuestionView.model_validate(question).model_dump(mode="json")
    return public_question(
        _PRACTICE_QUESTION.validate_python(question), attempt["question_version"]
    ).model_dump(mode="json")


async def _current_heads(conn, origin):
    attempts = await fetch_all(
        "SELECT * FROM learning_attempts WHERE owner_id=%s AND origin_kind=%s AND origin_id=%s ORDER BY question_id,attempt_id FOR SHARE",
        (origin.owner_id, origin.kind, origin.origin_id),
        conn=conn,
    )
    heads = {}
    for attempt in attempts:
        question = events._check_attempt(origin, attempt)
        head = await fetch_one(
            "SELECT a.* FROM learning_assessment_heads h JOIN assessment_records a ON a.assessment_id=h.assessment_id "
            "AND a.attempt_id=h.attempt_id AND a.owner_id=h.owner_id AND a.revision=h.revision WHERE h.attempt_id=%s AND h.owner_id=%s FOR SHARE",
            (attempt["attempt_id"], origin.owner_id),
            conn=conn,
        )
        if head is not None:
            projections._check_head(origin, attempt, question, head)
        heads[attempt["attempt_id"]] = head
    return list(attempts), heads


async def _next_reviews(conn, origin, concept_rows):
    ids = sorted(concept_rows)
    if not ids:
        return []
    rows = await fetch_all(
        "SELECT * FROM review_tasks WHERE owner_id=%s AND space_id=%s AND scope_revision=%s AND is_current=1 AND concept_id IN ("
        + ",".join(["%s"] * len(ids))
        + ") ORDER BY due_at,review_task_id",
        (origin.owner_id, origin.space["space_id"], origin.scope_revision, *ids),
        conn=conn,
    )
    return [
        reviews.review_view(
            row, space=origin.space, concept=concept_rows[row["concept_id"]]
        )
        for row in rows
    ]


async def _activity_data(owner_id, kind, origin_id):
    """Build text-bearing views while the complete source gate remains locked."""
    async with transaction() as conn:
        origin = await events._locked_origin(conn, owner_id, kind, origin_id)
        attempts, heads = await _current_heads(conn, origin)
        completion = await fetch_one(
            "SELECT * FROM learning_activity_completions WHERE owner_id=%s AND origin_kind=%s AND origin_id=%s",
            (owner_id, kind, origin_id),
            conn=conn,
        )
        assessment_set_hash = None
        projection_status, projection_revision = "not_ready", None
        if completion:
            projections._check_completion(origin, completion, attempts)
            assessment_set_hash = stable_hash(
                {
                    "completion_id": completion["completion_id"],
                    "answer_set_hash": completion["answer_set_hash"],
                    "heads": [
                        projections._head_identity(
                            attempt, heads[attempt["attempt_id"]]
                        )
                        for attempt in attempts
                    ],
                }
            )
            ready = all(
                head is not None
                and head["status"] == "graded"
                and head["confirmation"] == "confirmed"
                for head in heads.values()
            )
            receipt = await fetch_one(
                "SELECT projection_revision,projection_json FROM learning_projection_receipts WHERE owner_id=%s AND origin_kind=%s AND origin_id=%s AND completion_id=%s AND assessment_set_hash=%s AND rule_version=%s",
                (
                    owner_id,
                    kind,
                    origin_id,
                    completion["completion_id"],
                    assessment_set_hash,
                    RULE_VERSION,
                ),
                conn=conn,
            )
            if not ready:
                projection_status = "pending_assessments"
            elif (
                receipt
                and load(receipt["projection_json"], {}).get("status") == "projected"
            ):
                projection_status = "current"
                projection_revision = receipt["projection_revision"]
            else:
                failed = await fetch_one(
                    "SELECT 1 AS failed FROM learning_outbox o JOIN quiz_tasks j ON j.task_id=o.task_id AND j.user_id=o.owner_id WHERE o.owner_id=%s AND o.origin_kind=%s AND o.origin_id=%s AND o.processed_at IS NULL AND j.status IN ('failed','cancelled') LIMIT 1",
                    (owner_id, kind, origin_id),
                    conn=conn,
                )
                projection_status = "failed" if failed else "pending"
        concept_ids = sorted(
            {
                binding["concept_id"]
                for bindings in origin.bindings.values()
                for binding in bindings
            }
        )
        concept_rows = {
            concept_id: await concepts.owned_concept(owner_id, concept_id, conn=conn)
            for concept_id in concept_ids
        }
        next_reviews = await _next_reviews(conn, origin, concept_rows)
        public_heads = {
            attempt_id: _assessment_view(head) if head else None
            for attempt_id, head in heads.items()
        }
        results = [_result_status(head) for head in heads.values()]
        history = {
            "history_id": kind + ":" + origin_id,
            "origin_kind": kind,
            "origin_id": origin_id,
            "space_id": origin.space["space_id"],
            "scope_revision": origin.scope_revision,
            "title": origin.row["title"]
            if kind == "quiz"
            else load(origin.row["artifact_json"], {}).get("title", "练习"),
            "status": origin.row["status"],
            "occurred_at": reviews.timestamp(origin.row["created_at"]),
            "completed_at": reviews.timestamp(completion["completed_at"])
            if completion
            else None,
            "completion_id": completion["completion_id"] if completion else None,
            "question_count": len(origin.questions),
            "attempted_count": len(attempts),
            "confirmed_count": sum(
                result in {"correct", "wrong", "partial"} for result in results
            ),
            "correct_count": results.count("correct"),
            "wrong_count": results.count("wrong") + results.count("partial"),
            "pending_count": sum(
                result not in {"correct", "wrong", "partial"} for result in results
            ),
            "current_assessments": [
                public_heads[attempt["attempt_id"]]
                for attempt in attempts
                if public_heads[attempt["attempt_id"]] is not None
            ],
            "assessment_set_hash": assessment_set_hash,
            "projection_status": projection_status,
            "projection_revision": projection_revision,
            "concepts": [
                {"concept_id": item["concept_id"], "title": item["title"]}
                for item in concept_rows.values()
            ],
            "next_reviews": next_reviews,
            "scope": PublicResolvedScope.from_scope(origin.scope).model_dump(
                mode="json"
            ),
            "source_status": "active",
        }
        views = {}
        for attempt in attempts:
            ids = sorted(
                binding["concept_id"]
                for binding in origin.bindings.get(attempt["question_id"], [])
            )
            views[attempt["attempt_id"]] = {
                "item_id": attempt["attempt_id"],
                "attempt_id": attempt["attempt_id"],
                "origin_kind": kind,
                "origin_id": origin_id,
                "question_id": attempt["question_id"],
                "question_version": attempt["question_version"],
                "question_type": attempt["answer_kind"],
                "space_id": origin.space["space_id"],
                "scope_revision": origin.scope_revision,
                "occurred_at": reviews.timestamp(attempt["occurred_at"]),
                "help_usage": attempt["help_usage"],
                "association_status": "linked" if ids else "unlinked",
                "concepts": [
                    {
                        "concept_id": concept_id,
                        "title": concept_rows[concept_id]["title"],
                    }
                    for concept_id in ids
                ],
                "question": _public_question(origin, attempt),
                "answer": load(attempt["answer_json"]),
                "correct_answers": origin.questions[attempt["question_id"]].get(
                    "answer", []
                )
                if kind == "quiz"
                else [],
                "current_assessment": public_heads[attempt["attempt_id"]],
                "result_status": _result_status(heads[attempt["attempt_id"]]),
                "projection_status": projection_status,
                "next_reviews": [
                    review for review in next_reviews if review["concept_id"] in ids
                ],
                "source_status": "active",
            }
        return history, views


def _redacted_wrong(row):
    return {
        "item_id": row["item_id"],
        "attempt_id": row["attempt_id"],
        "origin_kind": row["origin_kind"],
        "origin_id": row["origin_id"],
        "question_id": row["question_id"],
        "question_version": None,
        "question_type": row["question_type"],
        "space_id": row["space_id"],
        "scope_revision": row["scope_revision"],
        "occurred_at": reviews.timestamp(row["occurred_at"]),
        "help_usage": "unknown",
        "association_status": "linked" if row["attempt_id"] else "unlinked",
        "concepts": [],
        "question": None,
        "answer": None,
        "correct_answers": [],
        "current_assessment": None,
        "result_status": row["result_status"],
        "projection_status": "not_ready",
        "next_reviews": [],
        "source_status": "revoked",
    }


async def _legacy_wrong(owner_id, row):
    async with transaction() as conn:
        detail = await learning_service.get_detail(
            owner_id, row["origin_id"], conn=conn
        )
        if detail["source_status"] == "source_revoked":
            return _redacted_wrong(row)
        question = next(
            (
                question
                for question in detail["questions"]
                if question["id"] == row["question_id"]
            ),
            None,
        )
        answer = next(
            (
                answer
                for answer in detail["answer_records"]
                if answer["question_id"] == row["question_id"]
            ),
            None,
        )
        if question is None or answer is None or answer["is_correct"]:
            return None
        return {
            **_redacted_wrong(row),
            "source_status": "active",
            "question": question,
            "question_type": question["type"],
            "answer": {"selected_answers": answer["selected_answers"]},
            "correct_answers": answer["correct_answers"],
            "feedback": answer["explanation"],
        }


async def list_wrong_questions(actor, filters=None, cursor=None, limit=20):
    filters = _filters(
        filters,
        {
            "space_id",
            "concept_id",
            "question_type",
            "status",
            "association_status",
            "origin_kind",
        },
    )
    context = reviews.page_context(actor.owner_id, "wrong_questions", filters)
    position = reviews.read_cursor(cursor, context, limit)
    # Scores are canonical decimal text. A SQL numeric cast can round a real
    # partial result to 1; the exact-one/zero predicates preserve that boundary.
    native = (
        "SELECT t.attempt_id AS item_id,t.attempt_id,t.origin_kind,t.origin_id,t.question_id,"
        "t.space_id,t.scope_revision,t.answer_kind AS question_type,t.occurred_at,"
        f"CASE WHEN {_ZERO} THEN 'wrong' ELSE 'partial' END AS result_status "
        "FROM learning_attempts t"
        + _HEAD_JOIN
        + f"WHERE t.owner_id=%s AND a.status='graded' AND a.confirmation='confirmed' AND {_NOT_FULL}"
    )
    legacy = (
        "SELECT CONCAT('legacy:',q.quiz_id,':',a.question_id) AS item_id,NULL AS attempt_id,'quiz' AS origin_kind,q.quiz_id AS origin_id,a.question_id,"
        "NULL AS space_id,NULL AS scope_revision,JSON_UNQUOTE(JSON_EXTRACT(j.question,'$.type')) AS question_type,a.created_at AS occurred_at,'wrong' AS result_status "
        "FROM quiz_answers a JOIN quiz_sessions q ON q.quiz_id=a.quiz_id AND q.user_id=a.user_id "
        "JOIN JSON_TABLE(q.questions_json,'$[*]' COLUMNS(question JSON PATH '$')) j ON JSON_UNQUOTE(JSON_EXTRACT(j.question,'$.id'))=a.question_id "
        "WHERE a.user_id=%s AND a.is_correct=FALSE AND NOT EXISTS (SELECT 1 FROM learning_attempts t WHERE t.owner_id=a.user_id AND t.origin_kind='quiz' AND t.origin_id=a.quiz_id AND t.question_id=a.question_id)"
    )
    imported = (
        "SELECT CONCAT('legacy:',q.quiz_id,':',JSON_UNQUOTE(JSON_EXTRACT(j.answer,'$.question_id'))) AS item_id,NULL AS attempt_id,'quiz' AS origin_kind,q.quiz_id AS origin_id,"
        "JSON_UNQUOTE(JSON_EXTRACT(j.answer,'$.question_id')) AS question_id,NULL AS space_id,NULL AS scope_revision,"
        "JSON_UNQUOTE(JSON_EXTRACT(k.question,'$.type')) AS question_type,a.created_at AS occurred_at,'wrong' AS result_status "
        "FROM answer_records a JOIN quiz_sessions q ON q.quiz_id=a.quiz_id AND q.user_id=a.user_id "
        "JOIN JSON_TABLE(a.records_json,'$[*]' COLUMNS(answer JSON PATH '$')) j "
        "JOIN JSON_TABLE(q.questions_json,'$[*]' COLUMNS(question JSON PATH '$')) k ON JSON_UNQUOTE(JSON_EXTRACT(k.question,'$.id'))=JSON_UNQUOTE(JSON_EXTRACT(j.answer,'$.question_id')) "
        "WHERE a.user_id=%s AND JSON_UNQUOTE(JSON_EXTRACT(j.answer,'$.is_correct'))='false' "
        "AND NOT EXISTS (SELECT 1 FROM quiz_answers qa WHERE qa.quiz_id=a.quiz_id AND qa.user_id=a.user_id) "
        "AND NOT EXISTS (SELECT 1 FROM learning_attempts t WHERE t.owner_id=a.user_id AND t.origin_kind='quiz' AND t.origin_id=a.quiz_id AND t.question_id=JSON_UNQUOTE(JSON_EXTRACT(j.answer,'$.question_id')))"
    )
    where, args = [], [actor.owner_id] * 3
    for field in ("space_id", "question_type", "origin_kind"):
        if field in filters:
            where.append(f"w.{field}=%s")
            args.append(filters[field])
    if "status" in filters:
        if filters["status"] not in {"wrong", "partial"}:
            raise AppError(422, "invalid_filter", "错题状态须为错误或部分正确")
        where.append("w.result_status=%s")
        args.append(filters["status"])
    if "concept_id" in filters:
        where.append(
            "EXISTS (SELECT 1 FROM question_concepts c WHERE c.owner_id=%s AND c.origin_kind=w.origin_kind AND c.origin_id=w.origin_id AND c.question_id=w.question_id AND c.concept_id=%s)"
        )
        args.extend((actor.owner_id, filters["concept_id"]))
    if "association_status" in filters:
        if filters["association_status"] not in {"linked", "unlinked"}:
            raise AppError(422, "invalid_filter", "无效的关联状态")
        where.append(
            "w.attempt_id IS "
            + ("NOT NULL" if filters["association_status"] == "linked" else "NULL")
        )
    if position:
        where.append("(w.occurred_at<%s OR (w.occurred_at=%s AND w.item_id<%s))")
        args.extend(
            (
                reviews.sql_time(position["time"]),
                reviews.sql_time(position["time"]),
                position["id"],
            )
        )
    rows = await fetch_all(
        "SELECT w.* FROM ("
        + native
        + " UNION ALL "
        + legacy
        + " UNION ALL "
        + imported
        + ") w "
        + ("WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY w.occurred_at DESC,w.item_id DESC LIMIT %s",
        (*args, limit + 1),
    )
    page, items, cache = list(rows[:limit]), [], {}
    for row in page:
        if row["attempt_id"] is None:
            item = await _legacy_wrong(actor.owner_id, row)
        else:
            identity = (row["origin_kind"], row["origin_id"])
            if identity not in cache:
                try:
                    cache[identity] = await _activity_data(actor.owner_id, *identity)
                except AppError as exc:
                    if exc.status != 404:
                        raise
                    cache[identity] = None
            data = cache[identity]
            item = (
                data[1].get(row["attempt_id"])
                if data is not None
                else _redacted_wrong(row)
            )
            if item is not None and item["result_status"] not in {"wrong", "partial"}:
                item = None
        if item is not None:
            items.append(item)
    return {
        "items": items,
        "next_cursor": reviews.write_cursor(
            context, page[-1]["occurred_at"], page[-1]["item_id"]
        )
        if len(rows) > limit
        else None,
    }


def _redacted_history(row):
    return {
        "history_id": row["history_id"],
        "origin_kind": row["origin_kind"],
        "origin_id": row["origin_id"],
        "space_id": row["space_id"],
        "scope_revision": row["scope_revision"],
        "title": "资料已失效的练习",
        "status": row["status"],
        "occurred_at": reviews.timestamp(row["occurred_at"]),
        "completed_at": None,
        "completion_id": None,
        "question_count": 0,
        "attempted_count": 0,
        "confirmed_count": 0,
        "correct_count": 0,
        "wrong_count": 0,
        "pending_count": 0,
        "current_assessments": [],
        "assessment_set_hash": None,
        "projection_status": "not_ready",
        "projection_revision": None,
        "concepts": [],
        "next_reviews": [],
        "scope": None,
        "source_status": "revoked",
    }


async def _legacy_history(owner_id, row):
    async with transaction() as conn:
        detail = await learning_service.get_detail(
            owner_id, row["origin_id"], conn=conn
        )
        view = _redacted_history(row)
        if detail["source_status"] == "source_revoked":
            return view
        answers = detail["answer_records"]
        quiz = await learning_service.owned_quiz(owner_id, row["origin_id"], conn=conn)
        raw_scope = load(quiz["source_scope_json"])
        return {
            **view,
            "title": detail["title"],
            "source_status": "active",
            "status": quiz["status"],
            "completed_at": reviews.timestamp(quiz["settled_at"])
            if quiz["status"] == "settled" and quiz["settled_at"] is not None
            else None,
            "question_count": len(detail["questions"]),
            "attempted_count": len(answers),
            "confirmed_count": len(answers),
            "correct_count": sum(answer["is_correct"] for answer in answers),
            "wrong_count": sum(not answer["is_correct"] for answer in answers),
            "scope": PublicResolvedScope.from_scope(
                ResolvedScope.model_validate(raw_scope)
            ).model_dump(mode="json")
            if raw_scope
            else None,
        }


async def list_learning_history(actor, filters=None, cursor=None, limit=20):
    filters = _filters(
        filters, {"space_id", "concept_id", "scope_revision", "status", "origin_kind"}
    )
    context = reviews.page_context(actor.owner_id, "learning_history", filters)
    position = reviews.read_cursor(cursor, context, limit)
    query = (
        "SELECT CONCAT('quiz:',q.quiz_id) AS history_id,'quiz' AS origin_kind,q.quiz_id AS origin_id,c.space_id,c.scope_revision,q.status,q.created_at AS occurred_at "
        "FROM quiz_sessions q LEFT JOIN learning_quiz_contexts c ON c.quiz_id=q.quiz_id AND c.owner_id=q.user_id WHERE q.user_id=%s "
        "UNION ALL SELECT CONCAT('practice:',p.practice_id) AS history_id,'practice' AS origin_kind,p.practice_id AS origin_id,p.space_id,p.scope_revision,p.status,p.created_at AS occurred_at "
        "FROM practice_sessions p WHERE p.owner_id=%s AND p.status IN ('ready','completed')"
    )
    where, args = [], [actor.owner_id, actor.owner_id]
    for field in ("space_id", "scope_revision", "status", "origin_kind"):
        if field in filters:
            where.append(f"x.{field}=%s")
            args.append(filters[field])
    if "concept_id" in filters:
        where.append(
            "EXISTS (SELECT 1 FROM question_concepts c WHERE c.owner_id=%s AND c.origin_kind=x.origin_kind AND c.origin_id=x.origin_id AND c.concept_id=%s)"
        )
        args.extend((actor.owner_id, filters["concept_id"]))
    if position:
        where.append("(x.occurred_at<%s OR (x.occurred_at=%s AND x.history_id<%s))")
        args.extend(
            (
                reviews.sql_time(position["time"]),
                reviews.sql_time(position["time"]),
                position["id"],
            )
        )
    rows = await fetch_all(
        "SELECT x.* FROM ("
        + query
        + ") x "
        + ("WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY x.occurred_at DESC,x.history_id DESC LIMIT %s",
        (*args, limit + 1),
    )
    items, page = [], list(rows[:limit])
    for row in page:
        if row["space_id"] is None:
            items.append(await _legacy_history(actor.owner_id, row))
            continue
        try:
            activity, _ = await _activity_data(
                actor.owner_id, row["origin_kind"], row["origin_id"]
            )
        except AppError as exc:
            if exc.status != 404:
                raise
            activity = _redacted_history(row)
        items.append(activity)
    return {
        "items": items,
        "next_cursor": reviews.write_cursor(
            context, page[-1]["occurred_at"], page[-1]["history_id"]
        )
        if len(rows) > limit
        else None,
    }


async def get_concept_progress(actor, concept_id):
    preview = await concepts.owned_concept(actor.owner_id, concept_id)
    async with transaction() as conn:
        space = await scopes.owned_space(
            actor.owner_id, preview["space_id"], conn=conn, lock=True
        )
        concept = await concepts.owned_concept(actor.owner_id, concept_id, conn=conn)
        states = await fetch_all(
            "SELECT * FROM learner_concept_state WHERE owner_id=%s AND space_id=%s AND concept_id=%s ORDER BY scope_revision",
            (actor.owner_id, space["space_id"], concept_id),
            conn=conn,
        )
        revisions = {
            concept["scope_revision"],
            space["title_scope_revision"],
            *(state["scope_revision"] for state in states),
        }
        await scopes.require_sources(
            [
                await scopes.stored_scope(
                    actor.owner_id, space["space_id"], revision, conn=conn
                )
                for revision in sorted(revisions)
            ],
            conn=conn,
        )
        current = await concepts.owned_concept(
            actor.owner_id, concept_id, conn=conn, lock=True
        )
        if (
            current["revision"] != concept["revision"]
            or current["scope_revision"] != concept["scope_revision"]
        ):
            raise not_found()
        rows = await fetch_all(
            "SELECT * FROM review_tasks WHERE owner_id=%s AND space_id=%s AND concept_id=%s AND is_current=1 ORDER BY scope_revision,due_at,review_task_id",
            (actor.owner_id, space["space_id"], concept_id),
            conn=conn,
        )
        next_reviews = [
            reviews.review_view(row, space=space, concept=concept) for row in rows
        ]
        views = [
            {
                "scope_revision": state["scope_revision"],
                "rule_version": state["rule_version"],
                "evidence_count": state["evidence_count"],
                "stage": state["stage"],
                "revision": state["revision"],
                "last_activity_local_date": state[
                    "last_activity_local_date"
                ].isoformat()
                if state["last_activity_local_date"]
                else None,
                "last_success_local_date": state["last_success_local_date"].isoformat()
                if state["last_success_local_date"]
                else None,
                "rule_due_at": reviews.timestamp(state["rule_due_at"]),
                "due_at": reviews.timestamp(state["due_at"]),
                "override_due_at": reviews.timestamp(state["override_due_at"]),
                "paused": bool(state["paused"]),
                "assessment_set_hash": state["assessment_set_hash"],
                "last_completion_id": state["last_completion_id"],
            }
            for state in states
        ]
        result = {
            "concept_id": concept_id,
            "space_id": space["space_id"],
            "title": concept["title"],
            "source_status": "active",
            "states": views,
            "next_reviews": next_reviews,
        }
    # Each history item uses its own full origin authorization. Historical
    # artifacts cannot inherit access solely from the concept's current title.
    history = await list_learning_history(actor, {"concept_id": concept_id}, None, 20)
    result["recent_history"] = history["items"]
    result["history_next_cursor"] = history["next_cursor"]
    return result
