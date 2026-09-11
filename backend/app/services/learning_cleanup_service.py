"""Post-revocation erasure of derived text, preserving identity and score facts.

This is called by the sole owner's cleanup job after the source tombstone has
committed. It must never be called while holding the source revocation lock.
"""

from pydantic import ValidationError

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict
from app.core.values import dump, load
from app.rag.contracts import ResolvedScope
from app.services import learning_scope_service as scopes
from app.services import practice_dependencies


def scrub_quiz_question(question):
    return {
        "id": question["id"],
        "type": question["type"],
        "stem": "",
        "options": [],
        "answer": [],
        "explanation": "",
        "knowledge_point": "",
        "difficulty": question.get("difficulty", "medium"),
        "citation_refs": [],
        "support_quotes": [],
        "image_status": "not_requested",
    }


def _uses_document(scope, doc_id):
    return any(
        item.get("doc_id") == doc_id for item in load(scope, {}).get("documents", [])
    )


async def _scrub_quiz(conn, owner_id, quiz):
    quiz_id = quiz["quiz_id"]
    await execute(
        "UPDATE quiz_sessions SET title='资料已失效的练习',summary='',user_input='',questions_json=%s,source_status='source_revoked' "
        "WHERE quiz_id=%s AND user_id=%s",
        (
            dump(
                [scrub_quiz_question(item) for item in load(quiz["questions_json"], [])]
            ),
            quiz_id,
            owner_id,
        ),
        conn=conn,
    )
    answers = await fetch_all(
        "SELECT question_id,receipt_json FROM quiz_answers WHERE quiz_id=%s AND user_id=%s ORDER BY question_id",
        (quiz_id, owner_id),
        conn=conn,
    )
    for answer in answers:
        receipt = load(answer["receipt_json"], {})
        record = receipt.get("answer_record")
        if record is not None:
            record.update(
                selected_answers=[],
                correct_answers=[],
                explanation="",
                citation_refs=[],
            )
        await execute(
            "UPDATE quiz_answers SET selected_json=JSON_ARRAY(),receipt_json=%s WHERE quiz_id=%s AND question_id=%s AND user_id=%s",
            (dump(receipt), quiz_id, answer["question_id"], owner_id),
            conn=conn,
        )
    legacy = await fetch_one(
        "SELECT records_json FROM answer_records WHERE quiz_id=%s AND user_id=%s",
        (quiz_id, owner_id),
        conn=conn,
    )
    if legacy:
        records = [
            {
                key: value
                for key, value in record.items()
                if key in {"question_id", "is_correct", "duration_ms"}
            }
            | {"selected_answers": []}
            for record in load(legacy["records_json"], [])
        ]
        await execute(
            "UPDATE answer_records SET records_json=%s WHERE quiz_id=%s AND user_id=%s",
            (dump(records), quiz_id, owner_id),
            conn=conn,
        )
    await execute(
        "UPDATE reports SET report_json=NULL,error_code='source_revoked' WHERE quiz_id=%s AND user_id=%s",
        (quiz_id, owner_id),
        conn=conn,
    )


async def _scrub_practice(conn, owner_id, practice_id):
    # P01 submission/completion receipts contain identities, not source text.
    # Keep them and the authoritative assessment numbers after removing the
    # duplicate private artifacts and requests used by generation/grading.
    await execute(
        "UPDATE practice_sessions SET generation_request_json=JSON_OBJECT(),artifact_json=NULL,"
        "help_usage_json=NULL,error_code='source_revoked' WHERE practice_id=%s AND owner_id=%s",
        (practice_id, owner_id),
        conn=conn,
    )
    # A frozen metadata dependency can be revoked without revoking the
    # activity's scope revision. Scrub its learning copies by origin as well.
    arguments = (practice_id, owner_id)
    await execute(
        "UPDATE assessment_records a JOIN learning_attempts t ON t.attempt_id=a.attempt_id AND t.owner_id=a.owner_id "
        "SET a.feedback=NULL,a.evidence_refs_json=NULL,a.criterion_results_json=NULL "
        "WHERE t.origin_kind='practice' AND t.origin_id=%s AND t.owner_id=%s",
        arguments,
        conn=conn,
    )
    await execute(
        "UPDATE learning_annotations a JOIN learning_attempts t ON t.attempt_id=a.attempt_id AND t.owner_id=a.owner_id "
        "SET a.payload_json=NULL WHERE t.origin_kind='practice' AND t.origin_id=%s AND t.owner_id=%s",
        arguments,
        conn=conn,
    )
    await execute(
        "UPDATE learning_attempts SET answer_json=NULL WHERE origin_kind='practice' AND origin_id=%s AND owner_id=%s",
        arguments,
        conn=conn,
    )
    await execute(
        "UPDATE learning_outbox SET payload_json=CASE WHEN "
        "REGEXP_LIKE(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.assessment_body_hash')),"
        "'^[0-9a-f]{64}$','c') THEN JSON_OBJECT('assessment_body_hash',"
        "JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.assessment_body_hash'))) ELSE JSON_OBJECT() END "
        "WHERE origin_kind='practice' AND origin_id=%s AND owner_id=%s",
        arguments,
        conn=conn,
    )
    await execute(
        "UPDATE review_task_events e JOIN review_tasks r ON r.review_task_id=e.review_task_id AND r.owner_id=e.owner_id "
        "SET e.payload_json=JSON_OBJECT() WHERE r.origin_kind='practice' AND r.origin_id=%s AND r.owner_id=%s",
        arguments,
        conn=conn,
    )
    await execute(
        "UPDATE review_tasks SET status='cancelled',paused=TRUE,is_current=NULL,last_error_code='source_revoked',"
        "revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE origin_kind='practice' AND origin_id=%s AND owner_id=%s "
        "AND status<>'completed' AND NOT(last_error_code <=> 'source_revoked')",
        arguments,
        conn=conn,
    )
    await execute(
        "UPDATE practice_grading_requests g JOIN practice_submissions s "
        "ON s.attempt_id=g.attempt_id AND s.owner_id=g.owner_id "
        "SET g.request_json=JSON_OBJECT(),g.artifact_json=NULL,g.error_code='source_revoked' "
        "WHERE s.practice_id=%s AND s.owner_id=%s",
        (practice_id, owner_id),
        conn=conn,
    )


async def _scrub_scope(conn, owner_id, space_id, revision):
    arguments = (space_id, revision, owner_id)
    await execute(
        "UPDATE learning_spaces SET title='资料已失效的学习空间',revision=revision+1,updated_at=UTC_TIMESTAMP(6) "
        "WHERE space_id=%s AND title_scope_revision=%s AND owner_id=%s AND title<>'资料已失效的学习空间'",
        arguments,
        conn=conn,
    )
    for table, title in (
        ("learning_goals", "资料已失效的学习目标"),
        ("learning_units", "资料已失效的学习单元"),
        ("learning_concepts", "资料已失效的概念"),
    ):
        # Table names are this fixed local allowlist; text and identities bind.
        await execute(
            f"UPDATE {table} SET title=%s,revision=revision+1,updated_at=UTC_TIMESTAMP(6) "
            "WHERE space_id=%s AND scope_revision=%s AND owner_id=%s AND title<>%s",
            (title, *arguments, title),
            conn=conn,
        )
    await execute(
        "UPDATE learning_quiz_contexts SET objectives_json=JSON_ARRAY(),coverage_plan_json=JSON_OBJECT() "
        "WHERE space_id=%s AND scope_revision=%s AND owner_id=%s",
        arguments,
        conn=conn,
    )
    await execute(
        "UPDATE assessment_records a JOIN learning_attempts t ON t.attempt_id=a.attempt_id AND t.owner_id=a.owner_id "
        "SET a.feedback=NULL,a.evidence_refs_json=NULL,a.criterion_results_json=NULL "
        "WHERE t.space_id=%s AND t.scope_revision=%s AND t.owner_id=%s",
        arguments,
        conn=conn,
    )
    await execute(
        "UPDATE learning_annotations a JOIN learning_attempts t ON t.attempt_id=a.attempt_id AND t.owner_id=a.owner_id "
        "SET a.payload_json=NULL WHERE t.space_id=%s AND t.scope_revision=%s AND t.owner_id=%s",
        arguments,
        conn=conn,
    )
    await execute(
        "UPDATE learning_attempts SET answer_json=NULL WHERE space_id=%s AND scope_revision=%s AND owner_id=%s",
        arguments,
        conn=conn,
    )
    await execute(
        # Keep only the server-generated opaque replay identity. MySQL may
        # render numeric JSON differently; scrubbed bodies cannot replace it.
        "UPDATE learning_outbox SET payload_json=CASE WHEN "
        "REGEXP_LIKE(JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.assessment_body_hash')),"
        "'^[0-9a-f]{64}$','c') THEN JSON_OBJECT('assessment_body_hash',"
        "JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.assessment_body_hash'))) ELSE JSON_OBJECT() END "
        "WHERE space_id=%s AND scope_revision=%s AND owner_id=%s",
        arguments,
        conn=conn,
    )
    await execute(
        "UPDATE review_task_events e JOIN review_tasks r ON r.review_task_id=e.review_task_id AND r.owner_id=e.owner_id "
        "SET e.payload_json=JSON_OBJECT() WHERE r.space_id=%s AND r.scope_revision=%s AND r.owner_id=%s",
        arguments,
        conn=conn,
    )
    await execute(
        "UPDATE review_tasks SET status='cancelled',paused=TRUE,is_current=NULL,last_error_code='source_revoked',"
        "revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE space_id=%s AND scope_revision=%s AND owner_id=%s "
        "AND status<>'completed' AND NOT(last_error_code <=> 'source_revoked')",
        arguments,
        conn=conn,
    )


async def purge_document(owner_id, doc_id):
    source = await fetch_one(
        "SELECT deleted_at FROM kb_documents WHERE doc_id=%s AND user_id=%s",
        (doc_id, owner_id),
    )
    if source is None or source["deleted_at"] is None:
        raise conflict("source_not_revoked", "只能清理已撤销的资料")
    affected = await fetch_all(
        "SELECT space_id,scope_revision FROM learning_scope_sources WHERE owner_id=%s AND doc_id=%s "
        "ORDER BY space_id,scope_revision",
        (owner_id, doc_id),
    )
    affected_pairs = {(row["space_id"], row["scope_revision"]) for row in affected}
    quizzes = await fetch_all(
        "SELECT q.*,c.space_id AS learning_space_id,c.scope_revision AS learning_scope_revision "
        "FROM quiz_sessions q LEFT JOIN learning_quiz_contexts c ON c.quiz_id=q.quiz_id AND c.owner_id=q.user_id "
        "WHERE q.user_id=%s ORDER BY q.quiz_id",
        (owner_id,),
    )
    quizzes = [
        quiz
        for quiz in quizzes
        if _uses_document(quiz["source_scope_json"], doc_id)
        or (quiz["learning_space_id"], quiz["learning_scope_revision"])
        in affected_pairs
    ]
    quiz_ids = {quiz["quiz_id"] for quiz in quizzes}
    practices = await fetch_all(
        "SELECT practice_id,owner_id,space_id,scope_revision,source_scope_json,generation_task_id,error_code,"
        + practice_dependencies.METADATA_SQL
        + " FROM practice_sessions WHERE owner_id=%s ORDER BY practice_id",
        (owner_id,),
    )
    spaces = {
        row["space_id"]: row["title_scope_revision"]
        for row in await fetch_all(
            "SELECT space_id,title_scope_revision FROM learning_spaces WHERE owner_id=%s",
            (owner_id,),
        )
    }
    concepts = {
        row["concept_id"]: row
        for row in await fetch_all(
            "SELECT concept_id,space_id,scope_revision FROM learning_concepts WHERE owner_id=%s",
            (owner_id,),
        )
    }
    bound_concepts = {}
    for row in await fetch_all(
        "SELECT origin_id,concept_id FROM question_concepts WHERE owner_id=%s AND origin_kind='practice'",
        (owner_id,),
    ):
        bound_concepts.setdefault(row["origin_id"], set()).add(row["concept_id"])
    affected_spaces = {space_id for space_id, _ in affected_pairs}
    affected_practices = []
    for session in practices:
        space_id = session["space_id"]
        revisions = {session["scope_revision"], spaces.get(space_id)}
        concept_ids = set(bound_concepts.get(session["practice_id"], ()))
        malformed = False
        try:
            scope = ResolvedScope.model_validate(load(session["source_scope_json"]))
            metadata = practice_dependencies.frozen_metadata(session, scope)
            revisions.update(metadata.revisions)
            concept_ids.update(metadata.concept_ids)
        except (AppError, ValidationError, ValueError, TypeError):
            # A scrubbed request or invalid envelope cannot establish that its
            # bodies are independent of this space's revoked source.
            malformed = True
        for concept_id in concept_ids:
            concept = concepts.get(concept_id)
            if concept is None or concept["space_id"] != space_id:
                malformed = True
            else:
                revisions.add(concept["scope_revision"])
        if (
            _uses_document(session["source_scope_json"], doc_id)
            or any((space_id, revision) in affected_pairs for revision in revisions)
            or (malformed and space_id in affected_spaces)
        ):
            affected_practices.append(session)
    practices = affected_practices
    practice_ids = {session["practice_id"] for session in practices}
    practice_tasks = {session["generation_task_id"] for session in practices}
    attempt_ids, grading_ids = set(), set()
    if practices:
        submissions = await fetch_all(
            "SELECT attempt_id,practice_id FROM practice_submissions WHERE owner_id=%s",
            (owner_id,),
        )
        attempt_ids = {
            row["attempt_id"]
            for row in submissions
            if row["practice_id"] in practice_ids
        }
        grades = await fetch_all(
            "SELECT grading_request_id,attempt_id,active_task_id FROM practice_grading_requests WHERE owner_id=%s",
            (owner_id,),
        )
        for grade in grades:
            if grade["attempt_id"] in attempt_ids:
                grading_ids.add(grade["grading_request_id"])
                if grade["active_task_id"]:
                    practice_tasks.add(grade["active_task_id"])
    jobs = await fetch_all(
        "SELECT task_id,quiz_id,scope_json,request_json FROM quiz_tasks WHERE user_id=%s AND kind<>'delete' ORDER BY task_id",
        (owner_id,),
    )
    affected_jobs = []
    for job in jobs:
        request = load(job["request_json"], {})
        learning_context = request.get("learning_context")
        if not isinstance(learning_context, dict):
            learning_context = {}
        if (
            job["quiz_id"] in quiz_ids
            or job["task_id"] in practice_tasks
            or _uses_document(job["scope_json"], doc_id)
            or (request.get("space_id"), request.get("scope_revision"))
            in affected_pairs
            or (
                learning_context.get("space_id"),
                learning_context.get("scope_revision"),
            )
            in affected_pairs
            or request.get("practice_id") in practice_ids
            or (
                request.get("origin_kind") == "practice"
                and request.get("origin_id") in practice_ids
            )
            or request.get("attempt_id") in attempt_ids
            or request.get("grading_request_id") in grading_ids
        ):
            affected_jobs.append(job)
    jobs = affected_jobs
    space_ids = (
        {row["space_id"] for row in affected}
        | {row["space_id"] for row in practices}
        | {row["learning_space_id"] for row in quizzes if row["learning_space_id"]}
    )
    async with transaction() as conn:
        # Common order: tasks, space roots, activity roots. Source tombstones
        # are read above; cleanup never reacquires a source write lock.
        for job in jobs:
            await fetch_one(
                "SELECT task_id FROM quiz_tasks WHERE task_id=%s AND user_id=%s FOR UPDATE",
                (job["task_id"], owner_id),
                conn=conn,
            )
        for space_id in sorted(space_ids):
            await scopes.owned_space(owner_id, space_id, conn=conn, lock=True)
        locked_quizzes = []
        for quiz in quizzes:
            locked = await fetch_one(
                "SELECT * FROM quiz_sessions WHERE quiz_id=%s AND user_id=%s FOR UPDATE",
                (quiz["quiz_id"], owner_id),
                conn=conn,
            )
            if locked:
                locked_quizzes.append(locked)
        locked_practices = []
        for session in practices:
            locked = await fetch_one(
                "SELECT practice_id FROM practice_sessions WHERE practice_id=%s AND owner_id=%s FOR UPDATE",
                (session["practice_id"], owner_id),
                conn=conn,
            )
            if locked:
                locked_practices.append(locked["practice_id"])
        for quiz in locked_quizzes:
            await _scrub_quiz(conn, owner_id, quiz)
        for practice_id in locked_practices:
            await _scrub_practice(conn, owner_id, practice_id)
        for row in affected:
            await _scrub_scope(conn, owner_id, row["space_id"], row["scope_revision"])
        for job in jobs:
            await execute(
                "UPDATE quiz_tasks SET user_input='',request_json=JSON_OBJECT(),result_json=NULL,error_message=NULL "
                "WHERE task_id=%s AND user_id=%s",
                (job["task_id"], owner_id),
                conn=conn,
            )
