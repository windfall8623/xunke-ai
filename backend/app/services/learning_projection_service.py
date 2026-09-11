"""Rebuild learning schedules from immutable completions and current heads.

Delivery order never changes the rule history. All publication, including an
outbox acknowledgment with no completion yet, belongs to the existing job's
lease transaction. Callers of rebuild_concept supply their own transaction and
must enter before taking source/concept/review locks (after their task, if any).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import ValidationError

from app.core.db import execute, fetch_all, fetch_one
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, load, uid
from app.learning.contracts import AssessmentDraft, ConceptState, LearningOutcome
from app.learning.review_rules import RULE_VERSION, next_schedule
from app.practice.contracts import PracticeArtifact
from app.rag.contracts import ResolvedScope, stable_hash
from app.services import job_service
from app.services import learning_concept_service as concepts
from app.services import learning_event_service as events
from app.services import learning_scope_service as scopes
from app.services import practice_dependencies


_EVENT_FIELDS = (
    "event_id",
    "event_type",
    "origin_kind",
    "origin_id",
    "space_id",
    "scope_revision",
    "attempt_id",
    "assessment_id",
    "completion_id",
)
_STATE_FIELDS = (
    "rule_version",
    "evidence_count",
    "stage",
    "last_activity_local_date",
    "last_success_local_date",
    "last_question_versions_json",
    "seen_question_versions_json",
    "rule_due_at",
    "due_at",
    "override_due_at",
    "assessment_set_hash",
    "last_completion_id",
)
_JSON_STATE_FIELDS = {"last_question_versions_json", "seen_question_versions_json"}
_INDEPENDENT_SUCCESS = {"independent_success", "independent_success_at_cap"}


@dataclass(frozen=True)
class _Activity:
    identity: events._Origin
    completion: dict | None
    attempts: list[dict]
    heads: dict[str, dict | None]
    assessment_set_hash: str | None
    ready: bool

    @property
    def key(self):
        return self.identity.kind, self.identity.origin_id


@dataclass(frozen=True)
class _History:
    owner_id: int
    space_id: str
    scope_revision: int
    concept_ids: list[str]
    activities: list[_Activity]


def _require_transaction(conn):
    if conn is None or not conn.get_transaction_status():
        raise ValueError("Learning projection requires the caller's transaction")


def _utc(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _sql_time(value):
    return _utc(value).replace(tzinfo=None) if value is not None else None


def _metadata_conflict():
    return conflict("metadata_revision_conflict", "学习元数据已经更新，请重试")


async def _bindings(conn, owner_id, kind, origin_id):
    return await fetch_all(
        "SELECT * FROM question_concepts WHERE owner_id=%s AND origin_kind=%s "
        "AND origin_id=%s ORDER BY question_id,concept_id FOR SHARE",
        (owner_id, kind, origin_id),
        conn=conn,
    )


async def _history_links(
    conn, owner_id, space_id, scope_revision, concept_ids, *, current=False
):
    return await fetch_all(
        "SELECT origin_kind,origin_id,question_id,question_version,concept_id "
        "FROM question_concepts WHERE owner_id=%s AND space_id=%s AND scope_revision=%s "
        "AND concept_id IN (" + ",".join(["%s"] * len(concept_ids)) + ") "
        "ORDER BY origin_kind,origin_id,question_id,concept_id"
        + (" FOR SHARE" if current else ""),
        (owner_id, space_id, scope_revision, *concept_ids),
        conn=conn,
    )


async def _unit_metadata(conn, owner_id, space_id, unit_id, *, current=False):
    row = await fetch_one(
        "SELECT u.unit_id,u.goal_id,u.scope_revision,u.revision AS unit_revision,"
        "g.scope_revision AS goal_scope_revision,g.revision AS goal_revision "
        "FROM learning_units u JOIN learning_goals g ON g.goal_id=u.goal_id "
        "AND g.space_id=u.space_id AND g.owner_id=u.owner_id "
        "WHERE u.unit_id=%s AND u.space_id=%s AND u.owner_id=%s"
        + (" FOR SHARE" if current else ""),
        (unit_id, space_id, owner_id),
        conn=conn,
    )
    if row is None:
        raise not_found()
    return row


async def _authorized_history(
    conn,
    owner_id,
    space_id,
    scope_revision,
    *,
    concept_ids=None,
    trigger=None,
    task_scope=None,
    space=None,
):
    """Lock activity roots first, the complete source union next, then concepts.

    Binding and metadata previews may come from a pre-existing repeatable-read
    snapshot. Current reads must match those previews; a newly discovered root
    or provenance aborts instead of acquiring more roots/sources out of order.
    Assessment heads and completions are always read with current-read locks.
    """
    _require_transaction(conn)
    if space is None:
        space = await scopes.owned_space(owner_id, space_id, conn=conn, lock=True)
    trigger_preview = None
    if trigger is not None:
        trigger_preview = await fetch_all(
            "SELECT * FROM question_concepts WHERE owner_id=%s AND origin_kind=%s "
            "AND origin_id=%s ORDER BY question_id,concept_id",
            (owner_id, *trigger),
            conn=conn,
        )
        concept_ids = sorted({row["concept_id"] for row in trigger_preview})
    else:
        concept_ids = sorted(set(concept_ids or []))
    if not concept_ids:
        raise not_found()

    preview_links = await _history_links(
        conn, owner_id, space_id, scope_revision, concept_ids
    )
    keys = {(row["origin_kind"], row["origin_id"]) for row in preview_links}
    if trigger is not None:
        keys.add(trigger)
    roots = {}
    for kind, origin_id in sorted(keys):
        if kind == "quiz":
            root = await concepts._quiz_origin(
                conn, owner_id, origin_id, space_id, scope_revision
            )
        elif kind == "practice":
            root = await concepts._practice_origin(
                conn, owner_id, origin_id, space_id, scope_revision, metadata_only=True
            )
        else:
            raise not_found()
        roots[(kind, origin_id)] = root
    if preview_links != await _history_links(
        conn, owner_id, space_id, scope_revision, concept_ids, current=True
    ):
        raise conflict("projection_history_conflict", "学习活动记录已经更新，请重试")
    if trigger is not None and trigger_preview != await _bindings(
        conn, owner_id, *trigger
    ):
        raise conflict("question_binding_conflict", "题目概念关联已经更新，请重试")

    saved_scope = await scopes.stored_scope(
        owner_id, space_id, scope_revision, conn=conn
    )
    dependencies = [saved_scope]
    revisions = {scope_revision, space["title_scope_revision"]}
    included = []
    units = {}
    all_concept_ids = set(concept_ids)
    for (kind, origin_id), (row, actual_scope) in sorted(roots.items()):
        completion = await fetch_one(
            "SELECT * FROM learning_activity_completions WHERE owner_id=%s AND origin_kind=%s "
            "AND origin_id=%s FOR SHARE",
            (owner_id, kind, origin_id),
            conn=conn,
        )
        if completion is None and (kind, origin_id) != trigger:
            continue
        if not scopes.scope_covers(saved_scope, actual_scope):
            raise not_found()
        if (kind, origin_id) == trigger and task_scope != actual_scope:
            raise not_found()
        if (kind == "quiz" and row["source_status"] == "source_revoked") or (
            kind == "practice" and row["error_code"] == "source_revoked"
        ):
            raise AppError(404, "source_revoked", "关联资料已删除或授权已变更")
        bindings = await _bindings(conn, owner_id, kind, origin_id)
        all_concept_ids.update(item["concept_id"] for item in bindings)
        dependencies.append(actual_scope)
        if kind == "quiz":
            context = await fetch_one(
                "SELECT unit_id FROM learning_quiz_contexts WHERE quiz_id=%s AND owner_id=%s FOR SHARE",
                (origin_id, owner_id),
                conn=conn,
            )
            if context["unit_id"]:
                unit = await _unit_metadata(
                    conn, owner_id, space_id, context["unit_id"]
                )
                units[unit["unit_id"]] = unit
                revisions.update((unit["scope_revision"], unit["goal_scope_revision"]))
        else:
            metadata = practice_dependencies.frozen_metadata(row, actual_scope)
            if saved_scope != actual_scope:
                raise not_found()
            revisions.update(metadata.revisions)
            all_concept_ids.update(metadata.concept_ids)
        included.append((kind, origin_id, row, actual_scope, completion, bindings))

    concept_previews = []
    for concept_id in sorted(all_concept_ids):
        preview = await concepts.owned_concept(owner_id, concept_id, conn=conn)
        if preview["space_id"] != space_id:
            raise not_found()
        revisions.add(preview["scope_revision"])
        concept_previews.append(preview)
    if None in revisions:
        raise not_found()
    for revision in sorted(revisions - {scope_revision}):
        dependencies.append(
            await scopes.stored_scope(owner_id, space_id, revision, conn=conn)
        )
    # This shared helper preserves every original scope, version, build and
    # chapter distinction while locking their union in global doc_id order.
    await scopes.require_sources(dependencies, conn=conn)
    for unit_id, preview in sorted(units.items()):
        if preview != await _unit_metadata(
            conn, owner_id, space_id, unit_id, current=True
        ):
            raise _metadata_conflict()
    for preview in concept_previews:
        current = await concepts.owned_concept(
            owner_id, preview["concept_id"], conn=conn, lock=True
        )
        if any(
            current[key] != preview[key]
            for key in ("space_id", "scope_revision", "revision")
        ):
            raise _metadata_conflict()

    activities = []
    for kind, origin_id, row, actual_scope, completion, bindings in included:
        if kind == "quiz":
            versions = await concepts._checked_quiz_questions(
                conn, owner_id, row, actual_scope
            )
            questions = {item["id"]: item for item in load(row["questions_json"])}
        else:
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
        by_question = {}
        for binding in bindings:
            by_question.setdefault(binding["question_id"], []).append(binding)
        if set(by_question) != set(questions):
            raise conflict("question_binding_conflict", "活动需要完整的题目概念关联")
        identity = events._Origin(
            owner_id,
            kind,
            origin_id,
            space,
            scope_revision,
            row,
            actual_scope,
            questions,
            versions,
            by_question,
        )
        # Reuse the event writer's immutable version, coverage and answer checks;
        # do not introduce a second question-version or answer-hash algorithm.
        for question_id, (version, _) in versions.items():
            events._checked_question(identity, question_id, version)
        attempts = await fetch_all(
            "SELECT * FROM learning_attempts WHERE owner_id=%s AND origin_kind=%s "
            "AND origin_id=%s ORDER BY question_id,attempt_id FOR SHARE",
            (owner_id, kind, origin_id),
            conn=conn,
        )
        heads = {}
        for attempt in attempts:
            question = events._check_attempt(identity, attempt)
            head = await fetch_one(
                "SELECT a.* FROM learning_assessment_heads h JOIN assessment_records a "
                "ON a.assessment_id=h.assessment_id AND a.attempt_id=h.attempt_id "
                "AND a.owner_id=h.owner_id AND a.revision=h.revision "
                "WHERE h.attempt_id=%s AND h.owner_id=%s FOR SHARE",
                (attempt["attempt_id"], owner_id),
                conn=conn,
            )
            if head is not None:
                _check_head(identity, attempt, question, head)
            heads[attempt["attempt_id"]] = head
        assessment_set_hash = None
        ready = False
        if completion is not None:
            _check_completion(identity, completion, attempts)
            assessment_set_hash = stable_hash(
                {
                    "completion_id": completion["completion_id"],
                    "answer_set_hash": completion["answer_set_hash"],
                    "heads": [
                        _head_identity(attempt, heads[attempt["attempt_id"]])
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
        activities.append(
            _Activity(identity, completion, attempts, heads, assessment_set_hash, ready)
        )
    activities.sort(
        key=lambda item: (
            item.completion["completed_at"] if item.completion else datetime.max,
            *item.key,
            item.completion["completion_id"] if item.completion else "",
        )
    )
    return _History(owner_id, space_id, scope_revision, concept_ids, activities)


def _check_head(identity, attempt, question, head):
    try:
        draft = AssessmentDraft(
            **{
                key: head[key]
                for key in AssessmentDraft.model_fields
                if key not in {"evidence_refs", "criterion_results", "feedback"}
            },
            feedback=head["feedback"] or "",
            evidence_refs=load(head["evidence_refs_json"], []),
            criterion_results=load(head["criterion_results_json"], []),
        )
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        raise conflict("assessment_identity_conflict", "当前评分记录不完整") from exc
    if draft.independent_eligible and attempt["help_usage"] != "none":
        raise conflict("assessment_help_conflict", "独立评分与原帮助记录不一致")
    if identity.kind == "practice" and (
        draft.rubric_version != question["rubric"]["version"]
        or draft.rubric_hash != stable_hash(question["rubric"])
    ):
        raise conflict("rubric_version_conflict", "当前评分依据与题目版本不一致")
    evidence_ids = set(question["citation_refs"])
    for criterion in question.get("rubric", {}).get("criteria", []):
        evidence_ids.update(criterion["evidence_refs"])
    if not set(draft.evidence_refs) <= evidence_ids:
        raise conflict("assessment_evidence_conflict", "当前评分引用与题目不一致")


def _check_completion(identity, completion, attempts):
    fixed_ids = sorted(attempt["attempt_id"] for attempt in attempts)
    if (
        completion["space_id"] != identity.space["space_id"]
        or completion["scope_revision"] != identity.scope_revision
        or not fixed_ids
        or len(fixed_ids) != len(set(fixed_ids))
        or load(completion["attempt_ids_json"]) != fixed_ids
        or completion["answer_set_hash"] != stable_hash(fixed_ids)
        or {attempt["question_id"] for attempt in attempts} != set(identity.questions)
    ):
        raise conflict("completion_conflict", "活动完成记录与完整作答集合不一致")
    required_status = "settled" if identity.kind == "quiz" else "completed"
    if identity.row["status"] != required_status:
        raise conflict("activity_incomplete", "学习活动尚未完成结算")
    try:
        local_date = (
            _utc(completion["completed_at"])
            .astimezone(ZoneInfo(completion["effective_timezone"]))
            .date()
        )
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise conflict("completion_conflict", "活动完成时区记录无效") from exc
    if completion["activity_local_date"] != local_date:
        raise conflict("completion_conflict", "活动完成日期与冻结时区不一致")


def _head_identity(attempt, head):
    return {
        "attempt_id": attempt["attempt_id"],
        "question_version": attempt["question_version"],
        "help_usage": attempt["help_usage"],
        "assessment": None
        if head is None
        else {
            key: head[key]
            for key in (
                "assessment_id",
                "revision",
                "status",
                "score",
                "confirmation",
                "independent_eligible",
            )
        },
    }


def _concept_attempts(activity, concept_id):
    return [
        attempt
        for attempt in activity.attempts
        if any(
            binding["concept_id"] == concept_id
            for binding in activity.identity.bindings[attempt["question_id"]]
        )
    ]


def _derive(history, concept_id):
    state = ConceptState()
    evidence_count = 0
    sets = []
    last_completion_id = None
    for activity in history.activities:
        if activity.completion is None:
            continue
        attempts = _concept_attempts(activity, concept_id)
        if not attempts:
            continue
        versions = sorted({attempt["question_version"] for attempt in attempts})
        local_date = activity.completion["activity_local_date"]
        if activity.ready:
            heads = [activity.heads[attempt["attempt_id"]] for attempt in attempts]
            help_usage = (
                "hints"
                if any(item["help_usage"] == "hints" for item in attempts)
                else (
                    "unknown"
                    if any(item["help_usage"] == "unknown" for item in attempts)
                    else "none"
                )
            )
            outcome = LearningOutcome(
                status="graded",
                confirmation="confirmed",
                # The rule distinguishes full success from any partial/error;
                # min preserves that exact boundary without Decimal averaging.
                score=min(Decimal(head["score"]) for head in heads),
                independent_eligible=help_usage == "none"
                and all(head["independent_eligible"] for head in heads),
                help_usage=help_usage,
                question_versions=versions,
            )
            decision = next_schedule(
                state,
                outcome,
                _utc(activity.completion["completed_at"]),
                activity.completion["effective_timezone"],
            )
            success = decision.reason in _INDEPENDENT_SUCCESS
            evidence_count += int(success)
            state = state.model_copy(
                update={
                    "stage": decision.stage,
                    "due_at": decision.due_at,
                    "last_success_local_date": local_date
                    if success
                    else state.last_success_local_date,
                }
            )
        # Completion proves exposure even while a result awaits confirmation.
        # Its versions/date remain history; it supplies no score or success.
        state = state.model_copy(
            update={
                "last_activity_local_date": local_date,
                "last_question_versions": versions,
                "seen_question_versions": sorted(
                    set(state.seen_question_versions) | set(versions)
                ),
            }
        )
        last_completion_id = activity.completion["completion_id"]
        sets.append(
            {
                "completion_id": last_completion_id,
                "assessment_set_hash": activity.assessment_set_hash,
            }
        )
    return {
        "rule_version": RULE_VERSION,
        "evidence_count": evidence_count,
        "stage": state.stage,
        "last_activity_local_date": state.last_activity_local_date,
        "last_success_local_date": state.last_success_local_date,
        "last_question_versions_json": state.last_question_versions,
        "seen_question_versions_json": state.seen_question_versions,
        "rule_due_at": _sql_time(state.due_at),
        "assessment_set_hash": stable_hash(sets),
        "last_completion_id": last_completion_id,
    }


async def _store_states(conn, history):
    states = {}
    previous = {}
    for concept_id in history.concept_ids:
        previous[concept_id] = await fetch_one(
            "SELECT * FROM learner_concept_state WHERE owner_id=%s AND space_id=%s "
            "AND concept_id=%s AND scope_revision=%s FOR UPDATE",
            (history.owner_id, history.space_id, concept_id, history.scope_revision),
            conn=conn,
        )
    review_rows = await _locked_reviews(conn, history)
    for concept_id in history.concept_ids:
        params = (
            history.owner_id,
            history.space_id,
            concept_id,
            history.scope_revision,
        )
        old = previous[concept_id]
        derived = _derive(history, concept_id)
        current = next(
            (
                row
                for row in review_rows
                if row["concept_id"] == concept_id and row["is_current"] == 1
            ),
            None,
        )
        bound = _bound_completion(current, history, concept_id) if current else None
        # A manual date belongs to one occurrence. Only consumption of the
        # current binding clears it; corrections and older-event replays do not.
        derived["override_due_at"] = (
            old["override_due_at"] if old and bound is None else None
        )
        derived["due_at"] = (
            derived["override_due_at"]
            if derived["override_due_at"] is not None
            else derived["rule_due_at"]
        )
        if current and current["status"] in {"claimed", "running"} and bound is None:
            # Keep the effective due of an activity already in progress. Its
            # fresh rule recommendation is still available in rule_due_at.
            derived["due_at"] = current["due_at"]
        changed = old is None or any(
            (load(old[field]) if field in _JSON_STATE_FIELDS else old[field])
            != derived[field]
            for field in _STATE_FIELDS
        )
        if changed:
            values = tuple(
                dump(derived[field]) if field in _JSON_STATE_FIELDS else derived[field]
                for field in _STATE_FIELDS
            )
            if old is None:
                await execute(
                    "INSERT INTO learner_concept_state(owner_id,space_id,concept_id,scope_revision,"
                    + ",".join(_STATE_FIELDS)
                    + ",revision) VALUES("
                    + ",".join(["%s"] * (4 + len(_STATE_FIELDS)))
                    + ",1)",
                    (*params, *values),
                    conn=conn,
                )
            else:
                await execute(
                    "UPDATE learner_concept_state SET "
                    + ",".join(field + "=%s" for field in _STATE_FIELDS)
                    + ",revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE owner_id=%s "
                    "AND space_id=%s AND concept_id=%s AND scope_revision=%s",
                    (*values, *params),
                    conn=conn,
                )
        states[concept_id] = {
            **(old or {"paused": False, "override_due_at": None}),
            **derived,
            "revision": (old["revision"] if old else 0) + int(changed),
        }
    await _sync_reviews(conn, history, states, previous, review_rows)
    return states


async def _review_event(conn, review, event_type, previous_due_at, payload):
    # A rule-only update must not take a late FK lock on another running job:
    # that job may already hold its task lock while waiting for this space.
    # The existing claim event/occurrence retain the binding; the rule event
    # also records its identity in body-free audit metadata.
    task_id = review["task_id"] if event_type == "completed" else None
    if review["task_id"] and task_id is None:
        payload = {**payload, "bound_task_id": review["task_id"]}
    await execute(
        "INSERT INTO review_task_events(event_id,review_task_id,owner_id,event_type,revision,"
        "task_id,origin_kind,origin_id,previous_due_at,due_at,payload_json) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            uid("review_event"),
            review["review_task_id"],
            review["owner_id"],
            event_type,
            review["revision"],
            task_id,
            review["origin_kind"],
            review["origin_id"],
            previous_due_at,
            review["due_at"],
            dump(payload),
        ),
        conn=conn,
    )


def _bound_completion(review, history, concept_id):
    if review["status"] not in {"claimed", "running"}:
        return None
    for activity in history.activities:
        if (
            activity.key != (review["origin_kind"], review["origin_id"])
            or not activity.ready
        ):
            continue
        field = (
            "origin_task_id"
            if activity.identity.kind == "quiz"
            else "generation_task_id"
        )
        if activity.identity.row[field] != review["task_id"]:
            raise conflict("review_binding_conflict", "复习任务与完成活动不一致")
        if not _concept_attempts(activity, concept_id):
            raise conflict("review_binding_conflict", "复习概念与完成活动不一致")
        return activity
    return None


async def _new_review(conn, history, concept_id, state, schedule_seq):
    review = {
        "review_task_id": uid("review"),
        "owner_id": history.owner_id,
        "revision": 1,
        "task_id": None,
        "origin_kind": None,
        "origin_id": None,
        "due_at": state["due_at"],
    }
    await execute(
        "INSERT INTO review_tasks(review_task_id,owner_id,space_id,concept_id,scope_revision,"
        "schedule_seq,rule_version,status,paused,rule_due_at,due_at,override_due_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,'scheduled',%s,%s,%s,%s)",
        (
            review["review_task_id"],
            history.owner_id,
            history.space_id,
            concept_id,
            history.scope_revision,
            schedule_seq,
            RULE_VERSION,
            state["paused"],
            state["rule_due_at"],
            state["due_at"],
            state["override_due_at"],
        ),
        conn=conn,
    )
    await _review_event(
        conn,
        review,
        "scheduled",
        None,
        {
            "rule_version": RULE_VERSION,
            "rule_due_at": state["rule_due_at"],
            "state_revision": state["revision"],
            "assessment_set_hash": state["assessment_set_hash"],
        },
    )


async def _locked_reviews(conn, history):
    return await fetch_all(
        "SELECT * FROM review_tasks WHERE owner_id=%s AND space_id=%s AND scope_revision=%s "
        "AND concept_id IN (" + ",".join(["%s"] * len(history.concept_ids)) + ") "
        "ORDER BY review_task_id FOR UPDATE",
        (
            history.owner_id,
            history.space_id,
            history.scope_revision,
            *history.concept_ids,
        ),
        conn=conn,
    )


async def _sync_reviews(conn, history, states, previous, rows):
    for concept_id, state in states.items():
        occurrences = [row for row in rows if row["concept_id"] == concept_id]
        current = next((row for row in occurrences if row["is_current"] == 1), None)
        latest = max(occurrences, key=lambda row: row["schedule_seq"], default=None)
        bound = _bound_completion(current, history, concept_id) if current else None
        if bound is not None:
            await execute(
                "UPDATE review_tasks SET status='completed',is_current=NULL,completed_at=%s,"
                "revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE review_task_id=%s AND owner_id=%s",
                (
                    bound.completion["completed_at"],
                    current["review_task_id"],
                    history.owner_id,
                ),
                conn=conn,
            )
            await _review_event(
                conn,
                {**current, "revision": current["revision"] + 1},
                "completed",
                current["due_at"],
                {
                    "completion_id": bound.completion["completion_id"],
                    "assessment_set_hash": bound.assessment_set_hash,
                },
            )
            current = None
        if current is not None:
            due = current["due_at"]
            if current["status"] == "scheduled" and current["override_due_at"] is None:
                due = state["rule_due_at"]
            if due is None:
                # A correction can remove the last confirmed rule suggestion.
                # Keep the immutable occurrence and its due, but free its slot.
                await execute(
                    "UPDATE review_tasks SET status='cancelled',is_current=NULL,rule_due_at=NULL,"
                    "last_error_code='assessment_pending',rule_version=%s,revision=revision+1,"
                    "updated_at=UTC_TIMESTAMP(6) WHERE review_task_id=%s AND owner_id=%s",
                    (RULE_VERSION, current["review_task_id"], history.owner_id),
                    conn=conn,
                )
                await _review_event(
                    conn,
                    {**current, "revision": current["revision"] + 1},
                    "cancelled",
                    current["due_at"],
                    {
                        "reason": "assessment_pending",
                        "state_revision": state["revision"],
                    },
                )
            elif (
                current["rule_version"],
                current["rule_due_at"],
                current["due_at"],
            ) != (RULE_VERSION, state["rule_due_at"], due):
                await execute(
                    "UPDATE review_tasks SET rule_version=%s,rule_due_at=%s,due_at=%s,"
                    "revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE review_task_id=%s AND owner_id=%s",
                    (
                        RULE_VERSION,
                        state["rule_due_at"],
                        due,
                        current["review_task_id"],
                        history.owner_id,
                    ),
                    conn=conn,
                )
                await _review_event(
                    conn,
                    {**current, "revision": current["revision"] + 1, "due_at": due},
                    "rule_updated",
                    current["due_at"],
                    {
                        "rule_version": RULE_VERSION,
                        "rule_due_at": state["rule_due_at"],
                        "state_revision": state["revision"],
                        "assessment_set_hash": state["assessment_set_hash"],
                    },
                )
            continue
        if state["due_at"] is None:
            continue
        old = previous[concept_id]
        new_completion = (
            old is None or old["last_completion_id"] != state["last_completion_id"]
        )
        if (
            latest
            and latest["status"] in {"failed", "cancelled"}
            and latest["last_error_code"] != "assessment_pending"
            and not new_completion
            and bound is None
        ):
            # A replay/correction is not the user's explicit retry operation.
            continue
        await _new_review(
            conn,
            history,
            concept_id,
            state,
            (latest["schedule_seq"] if latest else 0) + 1,
        )


async def rebuild_concept(conn, owner_id, space_id, concept_id, scope_revision) -> None:
    """Recompute one concept from current authoritative history in the caller TX."""
    history = await _authorized_history(
        conn,
        owner_id,
        space_id,
        scope_revision,
        concept_ids=[concept_id],
    )
    await _store_states(conn, history)


def _checked_job(delivered, current):
    if (
        current["kind"] != "learning_project"
        or current["operation"] != "learning.project"
        or current["mode"] != "production"
    ):
        raise not_found()
    if any(
        delivered.get(field) != current[field]
        for field in ("task_id", "user_id", "kind", "operation", "mode", "request_hash")
    ):
        raise not_found()
    if (
        delivered.get("request") != current["request"]
        or delivered.get("scope") != current["scope"]
    ):
        raise not_found()
    request = current["request"]
    if (
        not isinstance(request, dict)
        or not set(_EVENT_FIELDS) <= set(request)
        or set(request) - set(_EVENT_FIELDS) - {"assessment_body_hash"}
    ):
        raise not_found()
    if (
        current["request_hash"] != digest(dump(request))
        or current["idempotency_key"] != f"learning_project:{request['event_id']}"
    ):
        raise not_found()
    try:
        scope = ResolvedScope.model_validate(current["scope"])
    except (ValidationError, ValueError, TypeError) as exc:
        raise not_found() from exc
    if (
        scope.owner_id != current["user_id"]
        or scope.namespace != "production"
        or not scope.documents
    ):
        raise not_found()
    return request, scope


async def _checked_event(conn, current, request):
    event = await fetch_one(
        "SELECT * FROM learning_outbox WHERE event_id=%s AND owner_id=%s FOR UPDATE",
        (request["event_id"], current["user_id"]),
        conn=conn,
    )
    if (
        event is None
        or event["task_id"] != current["task_id"]
        or event["published_at"] is None
    ):
        raise not_found()
    if (
        any(event[field] != request[field] for field in _EVENT_FIELDS)
        or load(event["payload_json"]) != request
    ):
        raise not_found()
    return event


async def _check_event_fact(conn, event, activity):
    if event["event_type"] == "learning_activity_completed":
        if (
            activity.completion is None
            or event["completion_id"] != activity.completion["completion_id"]
        ):
            raise not_found()
    elif event["event_type"] == "learning_assessment":
        if event["attempt_id"] not in {
            attempt["attempt_id"] for attempt in activity.attempts
        }:
            raise not_found()
        fact = await fetch_one(
            "SELECT assessment_id FROM assessment_records WHERE assessment_id=%s "
            "AND attempt_id=%s AND owner_id=%s FOR SHARE",
            (event["assessment_id"], event["attempt_id"], event["owner_id"]),
            conn=conn,
        )
        if fact is None:
            raise not_found()
    else:
        raise not_found()


def _receipt_result(event, receipt):
    return {
        "event_id": event["event_id"],
        "status": load(receipt["projection_json"])["status"],
        "receipt_id": receipt["receipt_id"],
        "completion_id": receipt["completion_id"],
        "projection_revision": receipt["projection_revision"],
        "rule_version": receipt["rule_version"],
    }


async def _project(conn, current, request, task_scope):
    owner_id, space_id = current["user_id"], request["space_id"]
    space = await scopes.owned_space(owner_id, space_id, conn=conn, lock=True)
    event = await _checked_event(conn, current, request)
    history = await _authorized_history(
        conn,
        owner_id,
        space_id,
        event["scope_revision"],
        trigger=(event["origin_kind"], event["origin_id"]),
        task_scope=task_scope,
        space=space,
    )
    activity = next(
        item
        for item in history.activities
        if item.key == (event["origin_kind"], event["origin_id"])
    )
    await _check_event_fact(conn, event, activity)
    if event["processed_at"] is not None:
        # Normal replay uses the committed task result. An explicitly repaired
        # task with no saved result can still acknowledge without rebuilding.
        saved = current["result"]
        if isinstance(saved, dict) and saved.get("event_id") == event["event_id"]:
            return saved
        return {"event_id": event["event_id"], "status": "already_processed"}
    if activity.completion is None:
        result = {"event_id": event["event_id"], "status": "pending_completion"}
    else:
        receipts = await fetch_all(
            "SELECT * FROM learning_projection_receipts WHERE owner_id=%s AND origin_kind=%s "
            "AND origin_id=%s ORDER BY projection_revision,receipt_id FOR UPDATE",
            (owner_id, event["origin_kind"], event["origin_id"]),
            conn=conn,
        )
        receipt = next(
            (
                item
                for item in receipts
                if item["event_id"] == event["event_id"]
                or (
                    item["assessment_set_hash"] == activity.assessment_set_hash
                    and item["rule_version"] == RULE_VERSION
                )
            ),
            None,
        )
        if receipt is not None and (
            receipt["completion_id"] != activity.completion["completion_id"]
            or any(
                receipt[field] != event[field]
                for field in (
                    "owner_id",
                    "origin_kind",
                    "origin_id",
                    "space_id",
                    "scope_revision",
                )
            )
        ):
            raise conflict("projection_receipt_conflict", "投影回执与原活动不一致")
        if receipt is None:
            states = await _store_states(conn, history)
            revision = (
                max((item["projection_revision"] for item in receipts), default=0) + 1
            )
            receipt = {
                "receipt_id": uid("projection"),
                "completion_id": activity.completion["completion_id"],
                "projection_revision": revision,
                "rule_version": RULE_VERSION,
                "projection_json": {
                    "status": "projected" if activity.ready else "pending_assessments",
                    "concepts": {
                        concept_id: {
                            key: state[key]
                            for key in (
                                "stage",
                                "evidence_count",
                                "rule_due_at",
                                "revision",
                            )
                        }
                        for concept_id, state in states.items()
                    },
                },
            }
            await execute(
                "INSERT INTO learning_projection_receipts(receipt_id,event_id,owner_id,completion_id,"
                "origin_kind,origin_id,space_id,scope_revision,assessment_set_hash,rule_version,projection_json,projection_revision) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    receipt["receipt_id"],
                    event["event_id"],
                    owner_id,
                    receipt["completion_id"],
                    event["origin_kind"],
                    event["origin_id"],
                    space_id,
                    event["scope_revision"],
                    activity.assessment_set_hash,
                    RULE_VERSION,
                    dump(receipt["projection_json"]),
                    revision,
                ),
                conn=conn,
            )
        result = _receipt_result(event, receipt)
    await execute(
        "UPDATE learning_outbox SET processed_at=UTC_TIMESTAMP(6) WHERE event_id=%s AND owner_id=%s",
        (event["event_id"], owner_id),
        conn=conn,
    )
    return result


async def project_activity(job) -> None:
    """Consume one SQL outbox job without models or a second queue."""
    result = {}

    async def publish(current, public, conn):
        request, scope = _checked_job(job, current)
        public.update(await _project(conn, current, request, scope))
        # Recheck elapsed expiry/deadline before committing the publication.
        # Any failure rolls back the state, occurrence, receipt and event ack.
        await job_service.locked_job(job, conn)

    await job_service.complete_job(job, result, publisher=publish)
