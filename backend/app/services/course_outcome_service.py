"""Course goal identities and a read-only projection of verified learning facts."""

from collections import defaultdict

from app.core.db import execute, fetch_all, transaction
from app.core.values import dump, iso, load, uid
from app.models.course_outcome import (
    CourseCriterion, CourseCriterionOutcome, CourseEvidenceRef, CourseOutcomeSummary,
)
from app.rag.contracts import stable_hash
from app.services import course_read


def criterion_view(row):
    return CourseCriterion(
        course_criterion_id=row["course_criterion_id"],
        course_criterion_ref=row["course_criterion_ref"],
        criteria_revision=row["criteria_revision"], description=row["description"],
        evidence_type=row["evidence_type"], expectation=row["expectation"],
        lesson_ids=load(row["lesson_ids_json"], []), origin=row["origin"],
    )


async def criterion_rows(owner, course_id, revision, *, conn=None):
    return await fetch_all(
        "SELECT * FROM learning_course_criteria WHERE course_id=%s AND owner_id=%s "
        "AND criteria_revision=%s AND revoked_at IS NULL ORDER BY position",
        (course_id, owner, revision), conn=conn,
    )


async def publish_course_criteria(conn, owner, course_id, draft):
    """Called after lesson insertion within the fenced outline publication tx."""
    course = await course_read.owned_course(owner, course_id, conn=conn, lock=True)
    await course_read.authorize_course(course, conn=conn)
    raw = draft.model_dump(mode="json") if hasattr(draft, "model_dump") else draft
    payload = (raw or {}).get("payload") or {}
    lessons = await fetch_all(
        "SELECT lesson_id,unit_json FROM learning_course_lessons "
        "WHERE course_id=%s AND owner_id=%s ORDER BY position", (course_id, owner), conn=conn,
    )
    units = [(lesson["lesson_id"], load(lesson["unit_json"], {})) for lesson in lessons]
    origin = "generated_v2" if raw.get("schema_version") == "xunke-teach.v2" else "legacy_unmapped"
    definitions = payload.get("course_criteria", []) if origin == "generated_v2" else [
        dict(course_criterion_ref=f"legacy_{i}", description=text,
             evidence_type="recognition", expectation=text)
        for i, text in enumerate((payload.get("mission") or {}).get("success_criteria", []), 1)
        if isinstance(text, str) and text.strip()
    ]
    current_revision = course.get("criteria_revision", 1)
    existing = await criterion_rows(owner, course_id, current_revision, conn=conn)
    if not definitions:
        return [criterion_view(row) for row in existing]
    desired = []
    for definition in definitions:
        ref = definition["course_criterion_ref"]
        lesson_ids = [
            lesson_id for lesson_id, unit in units
            if origin == "legacy_unmapped" or ref in unit.get("course_criterion_refs", [])
        ]
        requirements = dict(
            evidence_type=definition["evidence_type"], all_mapped_items=True,
            minimum_items=1, independent_help="declared_none_without_recorded_hints",
        )
        frozen = dict(
            description=definition["description"], expectation=definition["expectation"],
            evidence_type=definition["evidence_type"], lesson_ids=sorted(lesson_ids),
            requirements=requirements, origin=origin,
        )
        desired.append(dict(**definition, lesson_ids=lesson_ids, requirements=requirements,
                            definition_hash=stable_hash(frozen)))
    if [(row["course_criterion_ref"], row["definition_hash"]) for row in existing] == [
        (item["course_criterion_ref"], item["definition_hash"]) for item in desired
    ]:
        return [criterion_view(row) for row in existing]
    revision = current_revision + 1 if existing else current_revision
    history = await fetch_all(
        "SELECT course_criterion_id,definition_hash FROM learning_course_criteria "
        "WHERE course_id=%s AND owner_id=%s AND revoked_at IS NULL ORDER BY criteria_revision DESC",
        (course_id, owner), conn=conn,
    )
    old_ids = {row["definition_hash"]: row["course_criterion_id"] for row in reversed(history)}
    used = set()
    for position, item in enumerate(desired):
        identity = old_ids.get(item["definition_hash"])
        identity = identity if identity and identity not in used else uid("course_criterion")
        used.add(identity)
        await execute(
            "INSERT INTO learning_course_criteria(course_criterion_id,criteria_revision,course_id,owner_id,"
            "course_criterion_ref,position,description,evidence_type,expectation,definition_hash,"
            "lesson_ids_json,requirements_json,origin) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (identity, revision, course_id, owner, item["course_criterion_ref"], position,
             item["description"], item["evidence_type"], item["expectation"], item["definition_hash"],
             dump(item["lesson_ids"]), dump(item["requirements"]), origin), conn=conn,
        )
    await execute(
        "UPDATE learning_courses SET criteria_revision=%s WHERE course_id=%s AND owner_id=%s",
        (revision, course_id, owner), conn=conn,
    )
    return [criterion_view(row) for row in await criterion_rows(owner, course_id, revision, conn=conn)]


async def get_course_criteria(owner, course_id, *, conn=None):
    course = await course_read.owned_course(owner, course_id, conn=conn)
    await course_read.authorize_course(course, conn=conn)
    rows = await criterion_rows(owner, course_id, course.get("criteria_revision", 1), conn=conn)
    if rows or not course["outline_json"]:
        return [criterion_view(row) for row in rows]
    # Lazy identity mapping is deterministic metadata, never a paid regeneration
    # or a learning/settlement event. The course lock prevents duplicate mapping.
    if conn is None:
        async with transaction() as tx:
            return await get_course_criteria(owner, course_id, conn=tx)
    return await publish_course_criteria(conn, owner, course_id, load(course["outline_json"], {}))


async def course_outcome_fields(owner, course_id, *, conn=None):
    criteria = await get_course_criteria(owner, course_id, conn=conn)
    course = await course_read.owned_course(owner, course_id, conn=conn)
    return dict(criteria_revision=course.get("criteria_revision", 1),
                course_criteria=[item.model_dump(mode="json") for item in criteria])


def project_criterion_outcome(criterion, definition_hash, lesson_versions, facts):
    """No model calls or writes; only the host may supply authoritative facts."""
    base = dict(course_criterion_id=criterion.course_criterion_id,
                criteria_revision=criterion.criteria_revision, title=criterion.description)

    def result(status, reason, fact=None):
        refs = [] if fact is None else fact.get("references", [fact["reference"]])
        return CourseCriterionOutcome(**base, status=status, reason=reason,
                                      evidence_refs=[CourseEvidenceRef.model_validate(ref) for ref in refs])

    if criterion.origin == "legacy_unmapped":
        return result("unverified", "旧课程目标尚未建立可信的题目对应关系，保持待验证。")
    if not facts:
        return result("unverified", "尚无已结算且明确对应本目标的学习证据。")
    current = [fact for fact in facts if fact["definition_hash"] == definition_hash
               and fact["lesson_versions"] == lesson_versions]
    if not current:
        return result("stale", "目标或关联课文已更新，旧证据保留为历史记录。",
                      max(facts, key=lambda fact: fact["reference"]["occurred_at"]))
    latest = max(current, key=lambda fact: fact["reference"]["occurred_at"])
    if (latest["reference"]["origin_kind"] == "self_check"
            or latest["status"] != "graded" or latest["confirmation"] != "confirmed"):
        return result("unverified", "当前只有已保存回答或暂定反馈，尚未形成正式确认的结果。", latest)
    if latest["passed"] is False:
        return result("needs_practice", "最新已确认检查仍有未通过项目，建议回到相关课时补练。", latest)
    if not latest["complete"]:
        return result("unverified", "本目标的必要检查尚未全部完成。", latest)
    if latest["evidence_type"] != criterion.evidence_type:
        return result("unverified", "当前题型只检查了部分能力，仍需符合本目标类型的应用或表达证据。", latest)
    if (latest["passed"] is True and latest["independent_eligible"]
            and latest["help_usage"] == "none"):
        return result("verified", "必要检查已确认通过；未使用帮助来自学习者声明，不代表已核验系统外独立性。", latest)
    return result("unverified", "检查成绩已保留，但帮助使用情况未知或存在提示，尚不能确认独立完成。", latest)


def _snapshot_criterion(snapshot, identity):
    return next((item for item in snapshot.get("criteria", [])
                 if item["course_criterion_id"] == identity), None)


async def _quiz_facts(owner, course_id, *, conn=None):
    rows = await fetch_all(
        "SELECT m.*,c.course_criterion_ref,c.definition_hash,a.snapshot_json,a.completion_json,"
        "q.settled_at AS quiz_settled_at FROM learning_course_assessment_questions m "
        "JOIN learning_course_criteria c ON c.course_criterion_id=m.course_criterion_id "
        "AND c.criteria_revision=m.criteria_revision AND c.owner_id=m.owner_id "
        "JOIN learning_course_assessments a ON a.course_assessment_id=m.course_assessment_id "
        "AND a.owner_id=m.owner_id JOIN quiz_sessions q ON q.quiz_id=m.quiz_id AND q.user_id=m.owner_id "
        "JOIN answer_records ar ON ar.quiz_id=q.quiz_id AND ar.user_id=q.user_id "
        "WHERE m.owner_id=%s AND m.course_id=%s AND q.status='settled' AND q.settled_at IS NOT NULL "
        "AND a.revoked_at IS NULL", (owner, course_id), conn=conn,
    )
    groups = defaultdict(list)
    for row in rows:
        groups[(row["course_assessment_id"], row["course_criterion_id"])].append(row)
    facts = defaultdict(list)
    for items in groups.values():
        row = items[0]
        criterion = _snapshot_criterion(load(row["snapshot_json"], {}), row["course_criterion_id"])
        if criterion is None:
            continue
        declaration = load(row["completion_json"], {})
        settlements = [load(item["settlement_json"]) for item in items]
        complete = all(item is not None for item in settlements)
        help_usage = declaration.get("help_usage", "unknown")
        references = [dict(origin_kind="quiz", origin_id=row["quiz_id"],
                           question_version=item["question_version"],
                           occurred_at=iso(row["quiz_settled_at"])) for item in items]
        facts[row["course_criterion_ref"]].append(dict(
            course_criterion_id=row["course_criterion_id"],
            definition_hash=row["definition_hash"], lesson_versions=criterion["lesson_versions"],
            evidence_type="recognition", status="graded", confirmation="confirmed",
            passed=all(item["is_correct"] for item in settlements if item is not None),
            complete=complete, independent_eligible=help_usage == "none"
            and declaration.get("system_hints_used") is False,
            help_usage=help_usage, help_usage_source=declaration.get("help_usage_source", "unknown"),
            reference=references[0], references=references,
        ))
    return facts


async def _application_facts(owner, course_id, *, conn=None):
    rows = await fetch_all(
        "SELECT a.*,p.application_task_id,p.help_usage,p.help_usage_source,t.course_criterion_ids_json,"
        "s.snapshot_json FROM learning_course_application_assessments a "
        "JOIN learning_course_application_attempts p ON p.latest_assessment_id=a.assessment_id "
        "AND p.attempt_id=a.attempt_id AND p.owner_id=a.owner_id "
        "JOIN learning_course_application_tasks t ON t.application_task_id=p.application_task_id "
        "AND t.owner_id=p.owner_id JOIN learning_course_assessments s "
        "ON s.course_assessment_id=t.course_assessment_id AND s.owner_id=t.owner_id "
        "LEFT JOIN learning_course_application_assessments successor "
        "ON successor.supersedes_assessment_id=a.assessment_id "
        "WHERE a.owner_id=%s AND a.course_id=%s AND successor.assessment_id IS NULL "
        "AND p.revoked_at IS NULL AND t.revoked_at IS NULL AND s.revoked_at IS NULL "
        "AND a.question_version=p.question_version AND a.question_version=t.question_version",
        (owner, course_id), conn=conn,
    )
    facts = defaultdict(list)
    for row in rows:
        snapshot, feedback = load(row["snapshot_json"], {}), load(row["feedback_json"], {})
        for identity in load(row["course_criterion_ids_json"], []):
            criterion = _snapshot_criterion(snapshot, identity)
            if criterion is None:
                continue
            results = feedback.get("criterion_results", [])
            facts[criterion["course_criterion_ref"]].append(dict(
                course_criterion_id=identity,
                definition_hash=criterion["definition_hash"], lesson_versions=criterion["lesson_versions"],
                evidence_type=criterion["evidence_type"], status=row["status"], confirmation=row["confirmation"],
                passed=(row["score"] == 1 and all(item.get("credit") == "full" for item in results))
                if row["status"] == "graded" else None,
                complete=bool(results), independent_eligible=bool(row["independent_eligible"]),
                help_usage=row["help_usage"], help_usage_source=row["help_usage_source"],
                reference=dict(origin_kind="course_application", origin_id=row["application_task_id"],
                               attempt_id=row["attempt_id"], assessment_id=row["assessment_id"],
                               question_version=row["question_version"], occurred_at=iso(row["created_at"])),
            ))
    return facts


async def get_course_outcomes(owner, course_id, *, conn=None):
    criteria = await get_course_criteria(owner, course_id, conn=conn)
    course = await course_read.owned_course(owner, course_id, conn=conn)
    rows = await criterion_rows(owner, course_id, course.get("criteria_revision", 1), conn=conn)
    definitions = {row["course_criterion_id"]: row for row in rows}
    lessons = await fetch_all(
        "SELECT lesson_id,content_version,status FROM learning_course_lessons "
        "WHERE course_id=%s AND owner_id=%s", (course_id, owner), conn=conn,
    )
    versions = {lesson["lesson_id"]: lesson["content_version"] for lesson in lessons}
    facts = await _quiz_facts(owner, course_id, conn=conn)
    applications = await _application_facts(owner, course_id, conn=conn)
    results = []
    for criterion in criteria:
        row = definitions[criterion.course_criterion_id]
        dependencies = {identity: versions.get(identity, 0) for identity in criterion.lesson_ids}
        # Published goal identities survive a local-ref rename. Same-ref
        # history is also retained so a changed definition is shown as stale;
        # definition and lesson-version checks below still decide eligibility.
        history = [
            fact for source in (facts, applications) for ref, items in source.items() for fact in items
            if fact["course_criterion_id"] == criterion.course_criterion_id or ref == criterion.course_criterion_ref
        ]
        outcome = project_criterion_outcome(
            criterion, row["definition_hash"], dependencies,
            history,
        )
        if not outcome.evidence_refs and any(
            lesson["lesson_id"] in criterion.lesson_ids and lesson["status"] == "material_gap"
            for lesson in lessons
        ):
            outcome.reason = "关联课时仍有资料缺口，本目标保持可见并等待补充依据。"
        results.append(outcome)
    await course_read.authorize_course(course, conn=conn)
    return CourseOutcomeSummary(course_id=course_id, criteria_revision=course.get("criteria_revision", 1), criteria=results)
