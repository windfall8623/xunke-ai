"""Append-only learning facts in the caller's authoritative transaction.

Callers holding an existing job lease must lock that job before entering here.
The immutable origin link is located without a lock, then the space and activity
roots are locked before all source dependencies and concepts. No function here
opens or commits a transaction, awards XP, or updates a learning projection.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import JsonValue, TypeAdapter, ValidationError

from app.core.db import execute, fetch_all, fetch_one
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, load, uid
from app.learning.contracts import (
    AssessmentDraft,
    AssessmentRef,
    AttemptRef,
    LearningAttemptDraft,
    LearningCompletionRef,
)
from app.models.learning import AnswerBody
from app.practice.contracts import PracticeArtifact, TypedAnswer
from app.rag.contracts import ResolvedScope, stable_hash
from app.services import job_service
from app.services import learning_concept_service as concepts
from app.services import learning_scope_service as scopes
from app.services import practice_dependencies


_TYPED_ANSWER = TypeAdapter(TypedAnswer)
_ANNOTATION_PAYLOAD = TypeAdapter(dict[str, JsonValue])


@dataclass(frozen=True)
class _Origin:
    owner_id: int
    kind: str
    origin_id: str
    space: dict
    scope_revision: int
    row: dict
    scope: ResolvedScope
    questions: dict
    versions: dict
    bindings: dict
    source_revoked: bool = False


def _require_transaction(conn):
    if conn is None or not conn.get_transaction_status():
        raise ValueError("Learning events require the caller's transaction")


async def _locked_origin(
    conn, owner_id, origin_kind, origin_id, *, allow_revoked_terminal=False
):
    if origin_kind == "quiz":
        link = await fetch_one(
            "SELECT c.space_id,c.scope_revision FROM learning_quiz_contexts c "
            "JOIN quiz_sessions q ON q.quiz_id=c.quiz_id AND q.user_id=c.owner_id "
            "WHERE c.quiz_id=%s AND c.owner_id=%s",
            (origin_id, owner_id),
            conn=conn,
        )
    elif origin_kind == "practice":
        link = await fetch_one(
            "SELECT space_id,scope_revision FROM practice_sessions "
            "WHERE practice_id=%s AND owner_id=%s",
            (origin_id, owner_id),
            conn=conn,
        )
    else:
        raise not_found()
    if link is None:
        raise not_found()
    space_id, revision = link["space_id"], link["scope_revision"]
    space = await scopes.owned_space(owner_id, space_id, conn=conn, lock=True)
    if origin_kind == "quiz":
        row = await fetch_one(
            "SELECT quiz_id,user_id,status,source_status,source_scope_json "
            "FROM quiz_sessions WHERE quiz_id=%s AND user_id=%s FOR UPDATE",
            (origin_id, owner_id),
            conn=conn,
        )
        context = await fetch_one(
            "SELECT space_id,scope_revision,unit_id,source_scope_json,scope_fingerprint "
            "FROM learning_quiz_contexts WHERE quiz_id=%s AND owner_id=%s FOR SHARE",
            (origin_id, owner_id),
            conn=conn,
        )
        if (
            row is None
            or context is None
            or (context["space_id"], context["scope_revision"]) != (space_id, revision)
        ):
            raise not_found()
        source_revoked = row["source_status"] == "source_revoked"
    else:
        row = await fetch_one(
            "SELECT practice_id,owner_id,space_id,scope_revision,status,error_code,"
            "source_scope_json,artifact_hash,"
            + practice_dependencies.METADATA_SQL
            + " FROM practice_sessions "
            "WHERE practice_id=%s AND owner_id=%s FOR UPDATE",
            (origin_id, owner_id),
            conn=conn,
        )
        context = {}
        if row is None or (row["space_id"], row["scope_revision"]) != (
            space_id,
            revision,
        ):
            raise not_found()
        source_revoked = row["error_code"] == "source_revoked"
    try:
        actual_scope = ResolvedScope.model_validate(load(row["source_scope_json"]))
        if origin_kind == "quiz":
            recorded_scope = ResolvedScope.model_validate(
                load(context["source_scope_json"])
            )
            if actual_scope.fingerprint != recorded_scope.fingerprint or (
                actual_scope.fingerprint != context["scope_fingerprint"]
            ):
                raise not_found()
    except (ValidationError, ValueError, TypeError) as exc:
        raise not_found() from exc
    saved_scope = await scopes.stored_scope(owner_id, space_id, revision, conn=conn)
    if not scopes.scope_covers(saved_scope, actual_scope):
        raise not_found()
    metadata = None
    if origin_kind == "practice" and not source_revoked:
        metadata = practice_dependencies.frozen_metadata(row, actual_scope)
        if saved_scope != actual_scope:
            raise not_found()
    bindings = await fetch_all(
        "SELECT * FROM question_concepts WHERE owner_id=%s AND origin_kind=%s "
        "AND origin_id=%s ORDER BY question_id,concept_id",
        (owner_id, origin_kind, origin_id),
        conn=conn,
    )
    concept_ids = sorted(
        {binding["concept_id"] for binding in bindings}
        | (set(metadata.concept_ids) if metadata else set())
    )
    concept_rows = []
    for concept_id in concept_ids:
        concept = await fetch_one(
            "SELECT concept_id,space_id,scope_revision,revision FROM learning_concepts "
            "WHERE concept_id=%s AND owner_id=%s",
            (concept_id, owner_id),
            conn=conn,
        )
        if concept is None or concept["space_id"] != space_id:
            raise not_found()
        concept_rows.append(concept)
    provenance_revisions = {
        revision,
        space["title_scope_revision"],
        *(concept["scope_revision"] for concept in concept_rows),
    }
    if metadata is not None:
        provenance_revisions.update(metadata.revisions)
    unit = None
    if context.get("unit_id"):
        unit = await fetch_one(
            "SELECT u.scope_revision,u.revision AS unit_revision,"
            "g.scope_revision AS goal_scope_revision,g.revision AS goal_revision "
            "FROM learning_units u JOIN learning_goals g ON g.goal_id=u.goal_id "
            "AND g.space_id=u.space_id AND g.owner_id=u.owner_id "
            "WHERE u.unit_id=%s AND u.space_id=%s AND u.owner_id=%s",
            (context["unit_id"], space_id, owner_id),
            conn=conn,
        )
        if unit is None:
            raise not_found()
        provenance_revisions.update(
            (unit["scope_revision"], unit["goal_scope_revision"])
        )
    if None in provenance_revisions:
        raise not_found()
    dependencies = [actual_scope]
    for provenance in sorted(provenance_revisions):
        dependencies.append(
            await scopes.stored_scope(owner_id, space_id, provenance, conn=conn)
        )
    try:
        await scopes.require_sources(dependencies, conn=conn)
    except AppError as exc:
        if not allow_revoked_terminal or exc.code != "source_revoked":
            raise
        source_revoked = True
    if source_revoked and not allow_revoked_terminal:
        raise AppError(404, "source_revoked", "关联资料已删除或授权已变更")
    # A revoked terminal write never loads question, answer or artifact bodies.
    questions, versions = {}, {}
    if not source_revoked and origin_kind == "quiz":
        row = await fetch_one(
            "SELECT * FROM quiz_sessions WHERE quiz_id=%s AND user_id=%s FOR UPDATE",
            (origin_id, owner_id),
            conn=conn,
        )
        versions = await concepts._checked_quiz_questions(
            conn, owner_id, row, actual_scope
        )
        questions = {item["id"]: item for item in load(row["questions_json"])}
    elif not source_revoked:
        from app.services.practice_service import _row_request_scope

        row = await fetch_one(
            "SELECT * FROM practice_sessions WHERE practice_id=%s AND owner_id=%s FOR UPDATE",
            (origin_id, owner_id),
            conn=conn,
        )
        _row_request_scope(row)
        versions = await concepts._checked_practice_questions(
            conn, owner_id, row, actual_scope
        )
        artifact = PracticeArtifact.model_validate(load(row["artifact_json"]))
        questions = {
            item.id: item.model_dump(mode="json") for item in artifact.questions
        }
    if unit is not None:
        current_unit = await fetch_one(
            "SELECT u.scope_revision,u.revision AS unit_revision,"
            "g.scope_revision AS goal_scope_revision,g.revision AS goal_revision "
            "FROM learning_units u JOIN learning_goals g ON g.goal_id=u.goal_id "
            "AND g.space_id=u.space_id AND g.owner_id=u.owner_id "
            "WHERE u.unit_id=%s AND u.space_id=%s AND u.owner_id=%s FOR SHARE",
            (context["unit_id"], space_id, owner_id),
            conn=conn,
        )
        if current_unit != unit:
            raise conflict("metadata_revision_conflict", "学习元数据已经更新，请重试")
    for previous in concept_rows:
        current = await fetch_one(
            "SELECT concept_id,space_id,scope_revision,revision FROM learning_concepts "
            "WHERE concept_id=%s AND owner_id=%s FOR UPDATE",
            (previous["concept_id"], owner_id),
            conn=conn,
        )
        # A caller can enter with an older repeatable-read snapshot. These
        # current reads must still match the provenance we just authorized.
        if current is None or any(
            current[key] != previous[key]
            for key in (
                "space_id",
                "scope_revision",
                "revision",
            )
        ):
            raise conflict("metadata_revision_conflict", "概念来源已经更新，请重试")
    current_bindings = await fetch_all(
        "SELECT * FROM question_concepts WHERE owner_id=%s AND origin_kind=%s "
        "AND origin_id=%s ORDER BY question_id,concept_id FOR SHARE",
        (owner_id, origin_kind, origin_id),
        conn=conn,
    )
    if bindings != current_bindings:
        raise conflict("question_binding_conflict", "题目概念关联已经更新，请重试")
    by_question = {}
    for binding in bindings:
        by_question.setdefault(binding["question_id"], []).append(binding)
    return _Origin(
        owner_id,
        origin_kind,
        origin_id,
        space,
        revision,
        row,
        actual_scope,
        questions,
        versions,
        by_question,
        source_revoked,
    )


def _checked_question(origin, question_id, question_version):
    question = origin.questions.get(question_id)
    if question is None:
        raise not_found()
    version, coverage_target = origin.versions[question_id]
    if question_version != version:
        raise conflict("question_version_conflict", "题目版本与已保存工件不一致")
    bindings = origin.bindings.get(question_id, [])
    if not bindings:
        raise not_found()
    if len(bindings) > 3 or any(
        (
            binding["space_id"],
            binding["scope_revision"],
            binding["question_version"],
            binding["coverage_target_id"],
        )
        != (
            origin.space["space_id"],
            origin.scope_revision,
            version,
            coverage_target,
        )
        for binding in bindings
    ):
        raise conflict(
            "question_binding_conflict", "题目关联与已保存的范围或版本不一致"
        )
    if origin.kind == "practice" and {item["concept_id"] for item in bindings} != set(
        question["concept_ids"]
    ):
        raise conflict("question_binding_conflict", "题目概念与已保存工件不一致")
    return question


def _canonical_answer(origin_kind, question, answer, duration_ms):
    try:
        if origin_kind == "quiz":
            if set(answer) != {"selected_answers"}:
                raise ValueError(
                    "Objective answer payload must contain only selected_answers"
                )
            body = AnswerBody.model_validate({**answer, "duration_ms": duration_ms})
            selected = sorted(body.selected_answers)
            allowed = {item["key"] for item in question["options"]}
            if (
                len(selected) != len(set(selected))
                or not set(selected) <= allowed
                or question["type"] in {"single", "judge"}
                and len(selected) != 1
            ):
                raise ValueError("Invalid objective answer")
            canonical = {"selected_answers": selected}
            # Preserve the legacy first-answer hash, including duration.
            response_hash = digest(dump({**canonical, "duration_ms": duration_ms}))
        else:
            typed = _TYPED_ANSWER.validate_python(answer)
            if typed.type != question["type"]:
                raise ValueError("Answer type differs from the saved question")
            canonical = typed.model_dump(mode="json")
            if typed.type == "cloze":
                if {item.blank_id for item in typed.blanks} != {
                    item["blank_id"] for item in question["rubric"]["slots"]
                }:
                    raise ValueError("Answer blanks differ from the saved question")
                canonical["blanks"] = sorted(
                    canonical["blanks"], key=lambda item: item["blank_id"]
                )
            # The practice response hash deliberately excludes duration/help.
            response_hash = stable_hash(canonical)
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise AppError(
            422, "invalid_learning_answer", "作答内容与题目格式不符"
        ) from exc
    return canonical, response_hash


def _attempt_ref(row):
    return AttemptRef(**{key: row[key] for key in AttemptRef.model_fields})


def _assessment_ref(row):
    return AssessmentRef(**{key: row[key] for key in AssessmentRef.model_fields})


def _completion_ref(row):
    return LearningCompletionRef(
        **{key: row[key] for key in LearningCompletionRef.model_fields}
    )


def _check_attempt(origin, row):
    if (row["space_id"], row["scope_revision"]) != (
        origin.space["space_id"],
        origin.scope_revision,
    ):
        raise not_found()
    question = _checked_question(origin, row["question_id"], row["question_version"])
    if row["answer_kind"] != question["type"] or row["answer_json"] is None:
        raise conflict("attempt_identity_conflict", "原作答与题目身份不一致")
    _, response_hash = _canonical_answer(
        origin.kind, question, load(row["answer_json"]), row["duration_ms"]
    )
    if response_hash != row["response_hash"]:
        raise conflict("attempt_identity_conflict", "原作答与已保存的校验信息不一致")
    return question


async def _terminal_question(conn, origin, attempt):
    """Use persistent identities after revocation, never the scrubbed bodies."""
    bindings = origin.bindings.get(attempt["question_id"], [])
    if (attempt["space_id"], attempt["scope_revision"]) != (
        origin.space["space_id"],
        origin.scope_revision,
    ) or not 1 <= len(bindings) <= 3:
        raise not_found()
    if (
        any(
            (
                binding["space_id"],
                binding["scope_revision"],
                binding["question_version"],
            )
            != (
                attempt["space_id"],
                attempt["scope_revision"],
                attempt["question_version"],
            )
            for binding in bindings
        )
        or len({binding["coverage_target_id"] for binding in bindings}) != 1
    ):
        raise conflict("question_binding_conflict", "题目关联与原作答身份不一致")
    if origin.kind == "quiz":
        if attempt["answer_kind"] not in {"single", "multiple", "judge"}:
            raise conflict("attempt_identity_conflict", "原作答题型不一致")
        # Objective quizzes have no separate rubric index. Their existing
        # current head must supply the persistent rubric identity below.
        return None
    question = await fetch_one(
        "SELECT question_version,rubric_version,rubric_hash FROM practice_questions "
        "WHERE practice_id=%s AND question_id=%s AND owner_id=%s FOR SHARE",
        (origin.origin_id, attempt["question_id"], origin.owner_id),
        conn=conn,
    )
    if (
        question is None
        or question["question_version"] != attempt["question_version"]
        or attempt["answer_kind"] not in {"cloze", "numeric", "short_answer"}
        or any(binding["coverage_target_id"] is not None for binding in bindings)
        or not origin.row["artifact_hash"]
    ):
        raise conflict("attempt_identity_conflict", "原作答与已保存的题目身份不一致")
    return question


async def _locked_attempt(conn, owner_id, attempt_id, *, minimal_terminal=False):
    preview = await fetch_one(
        "SELECT origin_kind,origin_id FROM learning_attempts WHERE attempt_id=%s AND owner_id=%s",
        (attempt_id, owner_id),
        conn=conn,
    )
    if preview is None:
        raise not_found()
    origin = await _locked_origin(
        conn,
        owner_id,
        preview["origin_kind"],
        preview["origin_id"],
        allow_revoked_terminal=minimal_terminal,
    )
    fields = (
        "attempt_id,owner_id,origin_kind,origin_id,question_id,question_version,"
        "space_id,scope_revision,answer_kind,help_usage"
        if origin.source_revoked
        else "*"
    )
    row = await fetch_one(
        f"SELECT {fields} FROM learning_attempts WHERE attempt_id=%s AND owner_id=%s FOR UPDATE",
        (attempt_id, owner_id),
        conn=conn,
    )
    if row is None or (row["origin_kind"], row["origin_id"]) != (
        origin.kind,
        origin.origin_id,
    ):
        raise not_found()
    question = (
        await _terminal_question(conn, origin, row)
        if origin.source_revoked
        else _check_attempt(origin, row)
    )
    return origin, row, question


async def _publish_event(
    conn,
    origin,
    event_type,
    *,
    attempt_id=None,
    assessment_id=None,
    completion_id=None,
    assessment_body_hash=None,
):
    event_id = uid("event")
    payload = {
        "event_id": event_id,
        "event_type": event_type,
        "origin_kind": origin.kind,
        "origin_id": origin.origin_id,
        "space_id": origin.space["space_id"],
        "scope_revision": origin.scope_revision,
        "attempt_id": attempt_id,
        "assessment_id": assessment_id,
        "completion_id": completion_id,
    }
    if assessment_body_hash is not None:
        # Preserve the original server-generated body identity even when
        # MySQL re-emits numeric criterion JSON with a different last digit.
        payload["assessment_body_hash"] = assessment_body_hash
    await execute(
        "INSERT INTO learning_outbox(event_id,owner_id,event_type,origin_kind,origin_id,space_id,"
        "scope_revision,attempt_id,assessment_id,completion_id,payload_json) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            event_id,
            origin.owner_id,
            event_type,
            origin.kind,
            origin.origin_id,
            origin.space["space_id"],
            origin.scope_revision,
            attempt_id,
            assessment_id,
            completion_id,
            dump(payload),
        ),
        conn=conn,
    )
    task = await job_service.enqueue_job(
        origin.owner_id,
        "learning_project",
        payload,
        f"learning_project:{event_id}",
        scope=origin.scope.model_dump(mode="json"),
        conn=conn,
    )
    await execute(
        "UPDATE learning_outbox SET task_id=%s,published_at=UTC_TIMESTAMP(6) "
        "WHERE event_id=%s AND owner_id=%s",
        (task["task_id"], event_id, origin.owner_id),
        conn=conn,
    )


async def record_attempt(
    conn, owner_id: int, draft: LearningAttemptDraft
) -> AttemptRef:
    _require_transaction(conn)
    draft = LearningAttemptDraft.model_validate(
        draft.model_dump() if isinstance(draft, LearningAttemptDraft) else draft
    )
    origin = await _locked_origin(conn, owner_id, draft.origin_kind, draft.origin_id)
    if (draft.space_id, draft.scope_revision) != (
        origin.space["space_id"],
        origin.scope_revision,
    ):
        raise not_found()
    question = _checked_question(origin, draft.question_id, draft.question_version)
    if draft.answer_kind != question["type"]:
        raise conflict("question_version_conflict", "作答题型与已保存的题目不一致")
    answer, response_hash = _canonical_answer(
        origin.kind, question, draft.answer_json, draft.duration_ms
    )
    if response_hash != draft.response_hash:
        raise conflict("response_hash_conflict", "作答内容与校验信息不一致")
    existing = await fetch_one(
        "SELECT * FROM learning_attempts WHERE owner_id=%s AND origin_kind=%s "
        "AND origin_id=%s AND question_id=%s FOR UPDATE",
        (owner_id, draft.origin_kind, draft.origin_id, draft.question_id),
        conn=conn,
    )
    if existing:
        immutable = (
            "question_version",
            "space_id",
            "scope_revision",
            "answer_kind",
            "response_hash",
            "duration_ms",
            "help_usage",
        )
        if any(existing[key] != getattr(draft, key) for key in immutable) or dump(
            load(existing["answer_json"])
        ) != dump(answer):
            raise conflict("answer_already_submitted", "此题已提交，不能修改原始作答")
        # occurred_at is server capture time, not a second submission identity.
        return _attempt_ref(existing)
    allowed_status = "active" if origin.kind == "quiz" else "ready"
    if origin.row["status"] != allowed_status:
        raise conflict("activity_completed", "此学习活动当前不能提交新作答")
    attempt_id = uid("attempt")
    await execute(
        "INSERT INTO learning_attempts(attempt_id,owner_id,origin_kind,origin_id,question_id,"
        "question_version,space_id,scope_revision,answer_kind,answer_json,response_hash,"
        "duration_ms,help_usage,occurred_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            attempt_id,
            owner_id,
            draft.origin_kind,
            draft.origin_id,
            draft.question_id,
            draft.question_version,
            draft.space_id,
            draft.scope_revision,
            draft.answer_kind,
            dump(answer),
            response_hash,
            draft.duration_ms,
            draft.help_usage,
            draft.occurred_at.astimezone(timezone.utc).replace(tzinfo=None),
        ),
        conn=conn,
    )
    return AttemptRef(
        attempt_id=attempt_id,
        owner_id=owner_id,
        origin_kind=draft.origin_kind,
        origin_id=draft.origin_id,
        question_id=draft.question_id,
    )


async def record_assessment(
    conn, owner_id: int, attempt_id: str, draft: AssessmentDraft
) -> AssessmentRef:
    _require_transaction(conn)
    draft = AssessmentDraft.model_validate(
        draft.model_dump() if isinstance(draft, AssessmentDraft) else draft
    )
    minimal_terminal = (
        draft.source == "model"
        and draft.status in {"failed", "cancelled"}
        and draft.confirmation == "provisional"
        and draft.score is None
        and not draft.independent_eligible
        and not draft.feedback
        and not draft.evidence_refs
        and not draft.criterion_results
    )
    origin, attempt, question = await _locked_attempt(
        conn, owner_id, attempt_id, minimal_terminal=minimal_terminal
    )
    if draft.independent_eligible and attempt["help_usage"] != "none":
        raise conflict(
            "assessment_help_conflict", "使用帮助或帮助情况未知的作答不能作为独立证据"
        )
    if origin.kind == "practice":
        rubric_version, rubric_hash = (
            (question["rubric_version"], question["rubric_hash"])
            if origin.source_revoked
            else (question["rubric"]["version"], stable_hash(question["rubric"]))
        )
        if (draft.rubric_version, draft.rubric_hash) != (rubric_version, rubric_hash):
            raise conflict("rubric_version_conflict", "评分依据与已保存的题目不一致")
    if not origin.source_revoked:
        evidence_ids = set(question["citation_refs"])
        for criterion in question.get("rubric", {}).get("criteria", []):
            evidence_ids.update(criterion["evidence_refs"])
        if not set(draft.evidence_refs) <= evidence_ids:
            raise conflict("assessment_evidence_conflict", "评分引用不属于已保存的题目")
    head = await fetch_one(
        "SELECT a.assessment_id,a.attempt_id,a.owner_id,a.revision,a.status,a.source,"
        "a.confirmation,a.rubric_version,a.rubric_hash,o.payload_json AS event_payload_json "
        "FROM learning_assessment_heads h JOIN assessment_records a "
        "ON a.assessment_id=h.assessment_id AND a.attempt_id=h.attempt_id "
        "AND a.owner_id=h.owner_id AND a.revision=h.revision "
        "LEFT JOIN learning_outbox o ON o.assessment_id=a.assessment_id "
        "AND o.owner_id=a.owner_id AND o.event_type='learning_assessment' "
        "WHERE h.attempt_id=%s AND h.owner_id=%s FOR UPDATE",
        (attempt_id, owner_id),
        conn=conn,
    )
    if origin.source_revoked:
        if head and (head["source"] == "human" or head["confirmation"] == "confirmed"):
            raise conflict(
                "assessment_terminal_conflict", "不能用终止状态替换人工或已确认评分"
            )
        if origin.kind == "quiz" and (
            head is None
            or (head["rubric_version"], head["rubric_hash"])
            != (draft.rubric_version, draft.rubric_hash)
        ):
            raise conflict("rubric_version_conflict", "评分依据与已保存的题目不一致")
    body = draft.model_dump(mode="json")
    body_hash = digest(dump(body))
    if (
        head
        and load(head["event_payload_json"], {}).get("assessment_body_hash")
        == body_hash
    ):
        return _assessment_ref(head)
    if draft.supersedes_assessment_id != (head["assessment_id"] if head else None):
        raise conflict(
            "assessment_revision_conflict", "评分版本已更新，请读取当前版本后重试"
        )
    if head is None and await fetch_one(
        "SELECT assessment_id FROM assessment_records WHERE attempt_id=%s AND owner_id=%s LIMIT 1",
        (attempt_id, owner_id),
        conn=conn,
    ):
        raise conflict("assessment_revision_conflict", "评分当前版本不完整")
    assessment_id = uid("assessment")
    revision = head["revision"] + 1 if head else 1
    await execute(
        "INSERT INTO assessment_records(assessment_id,attempt_id,owner_id,revision,status,score,source,"
        "confirmation,grader_version,rubric_version,rubric_hash,feedback,evidence_refs_json,"
        "criterion_results_json,supersedes_assessment_id,independent_eligible) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            assessment_id,
            attempt_id,
            owner_id,
            revision,
            draft.status,
            body["score"],
            draft.source,
            draft.confirmation,
            draft.grader_version,
            draft.rubric_version,
            draft.rubric_hash,
            draft.feedback,
            dump(body["evidence_refs"]),
            dump(body["criterion_results"]),
            draft.supersedes_assessment_id,
            draft.independent_eligible,
        ),
        conn=conn,
    )
    if head:
        changed = await execute(
            "UPDATE learning_assessment_heads SET assessment_id=%s,revision=%s,updated_at=UTC_TIMESTAMP(6) "
            "WHERE attempt_id=%s AND owner_id=%s AND assessment_id=%s AND revision=%s",
            (
                assessment_id,
                revision,
                attempt_id,
                owner_id,
                head["assessment_id"],
                head["revision"],
            ),
            conn=conn,
        )
        if changed != 1:
            raise conflict("assessment_revision_conflict", "评分当前版本已经更新")
    else:
        await execute(
            "INSERT INTO learning_assessment_heads(attempt_id,owner_id,assessment_id,revision) VALUES(%s,%s,%s,%s)",
            (attempt_id, owner_id, assessment_id, revision),
            conn=conn,
        )
    await _publish_event(
        conn,
        origin,
        "learning_assessment",
        attempt_id=attempt_id,
        assessment_id=assessment_id,
        assessment_body_hash=body_hash,
    )
    return AssessmentRef(
        assessment_id=assessment_id,
        attempt_id=attempt_id,
        revision=revision,
        status=draft.status,
        confirmation=draft.confirmation,
    )


async def record_completion(
    conn,
    owner_id: int,
    *,
    origin_kind: str,
    origin_id: str,
    attempt_ids: list[str],
    completed_at: datetime,
) -> LearningCompletionRef:
    _require_transaction(conn)
    origin = await _locked_origin(conn, owner_id, origin_kind, origin_id)
    if (
        not isinstance(attempt_ids, list)
        or not 1 <= len(attempt_ids) <= 10
        or any(
            not isinstance(value, str) or not 1 <= len(value) <= 64
            for value in attempt_ids
        )
        or len(attempt_ids) != len(set(attempt_ids))
    ):
        raise AppError(422, "invalid_attempt_set", "完成活动需要互不重复的完整作答集合")
    attempts = await fetch_all(
        "SELECT * FROM learning_attempts WHERE owner_id=%s AND origin_kind=%s AND origin_id=%s "
        "ORDER BY question_id,attempt_id FOR UPDATE",
        (owner_id, origin_kind, origin_id),
        conn=conn,
    )
    fixed_ids = sorted(attempt_ids)
    if fixed_ids != sorted(item["attempt_id"] for item in attempts) or {
        item["question_id"] for item in attempts
    } != set(origin.questions):
        raise conflict("activity_incomplete", "完成活动需要本次所有题目的固定作答集合")
    for attempt in attempts:
        _check_attempt(origin, attempt)
    answer_set_hash = stable_hash(fixed_ids)
    existing = await fetch_one(
        "SELECT * FROM learning_activity_completions WHERE owner_id=%s AND origin_kind=%s "
        "AND origin_id=%s FOR UPDATE",
        (owner_id, origin_kind, origin_id),
        conn=conn,
    )
    if existing:
        if (
            existing["space_id"] != origin.space["space_id"]
            or existing["scope_revision"] != origin.scope_revision
            or load(existing["attempt_ids_json"]) != fixed_ids
            or existing["answer_set_hash"] != answer_set_hash
        ):
            raise conflict("completion_conflict", "活动已经按另一组作答完成")
        return _completion_ref(existing)
    if origin.row["status"] not in (
        {"active", "settled"} if origin_kind == "quiz" else {"ready", "completed"}
    ):
        raise conflict("activity_unavailable", "本次学习活动当前不能完成")
    if not isinstance(completed_at, datetime):
        raise AppError(422, "invalid_completion_time", "需要有效的活动完成时间")
    # The existing server clock returns naive UTC; aware callers may use an offset.
    completed_utc = (
        completed_at.replace(tzinfo=timezone.utc)
        if completed_at.tzinfo is None
        else completed_at.astimezone(timezone.utc)
    )
    effective_timezone = origin.space["timezone"]
    try:
        local_date = completed_utc.astimezone(ZoneInfo(effective_timezone)).date()
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise conflict("timezone_conflict", "学习空间时区无效") from exc
    completion_id = uid("completion")
    await execute(
        "INSERT INTO learning_activity_completions(completion_id,owner_id,origin_kind,origin_id,space_id,"
        "scope_revision,attempt_ids_json,answer_set_hash,completed_at,effective_timezone,activity_local_date) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            completion_id,
            owner_id,
            origin_kind,
            origin_id,
            origin.space["space_id"],
            origin.scope_revision,
            dump(fixed_ids),
            answer_set_hash,
            completed_utc.replace(tzinfo=None),
            effective_timezone,
            local_date,
        ),
        conn=conn,
    )
    await _publish_event(
        conn, origin, "learning_activity_completed", completion_id=completion_id
    )
    return LearningCompletionRef(
        completion_id=completion_id,
        origin_kind=origin_kind,
        origin_id=origin_id,
        answer_set_hash=answer_set_hash,
    )


async def record_annotation(
    conn,
    owner_id: int,
    attempt_id: str,
    *,
    kind: str,
    payload: dict,
    key: str,
) -> str:
    _require_transaction(conn)
    if (
        kind not in {"self_review", "wrong_reason"}
        or not isinstance(key, str)
        or not key.strip()
        or len(key) > 128
    ):
        raise AppError(422, "invalid_annotation", "需要有效的自我核对或错因记录")
    try:
        payload = _ANNOTATION_PAYLOAD.validate_python(payload, strict=True)
        json.dumps(payload, allow_nan=False)
    except (ValidationError, ValueError, TypeError) as exc:
        raise AppError(
            422, "invalid_annotation", "记录内容必须是有效 JSON 对象"
        ) from exc
    await _locked_attempt(conn, owner_id, attempt_id)
    payload_hash = digest(dump({"kind": kind, "payload": payload}))
    existing = await fetch_one(
        "SELECT * FROM learning_annotations WHERE owner_id=%s AND attempt_id=%s "
        "AND idempotency_key=%s FOR UPDATE",
        (owner_id, attempt_id, key),
        conn=conn,
    )
    if existing:
        if existing["kind"] != kind or existing["payload_hash"] != payload_hash:
            raise conflict("annotation_conflict", "同一记录标识已经用于不同内容")
        return existing["annotation_id"]
    annotation_id = uid("annotation")
    await execute(
        "INSERT INTO learning_annotations(annotation_id,owner_id,attempt_id,author_id,kind,"
        "payload_json,idempotency_key,payload_hash,independent_eligible) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,FALSE)",
        (
            annotation_id,
            owner_id,
            attempt_id,
            owner_id,
            kind,
            dump(payload),
            key,
            payload_hash,
        ),
        conn=conn,
    )
    return annotation_id
