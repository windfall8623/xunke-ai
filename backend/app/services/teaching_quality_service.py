"""Durable role slots and private review history inside the existing course task."""

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import conflict
from app.core.values import digest, dump, load, now, uid
from app.models.teaching_quality import TeachingQualitySummary
from app.services import job_service
from app.teaching.policy import policy_from_job
from app.teaching.protocol import draft_hash
from app.teaching.review_contracts import TeachingReviewReport, require_review_binding

SLOTS = {"initial", "repair", "review_initial", "review_recheck"}
WARNING_TEXT = {
    "terminology_dense": "部分术语较集中，学习时可结合示例逐步核对。",
    "example_too_abstract": "部分例子仍较抽象，可通过新情境练习进一步检验。",
}


def _material_data(material):
    return {
        "catalog": material.catalog, "warnings": material.warnings,
        "evidence": {ref: item.model_dump(mode="json") for ref, item in material.evidence.items()},
    }


async def load_quality_material(job):
    """Resume the same retrieval snapshot; recovery must not buy another rerank."""
    from app.rag.contracts import DocumentEvidence
    from app.services import course_read
    from app.teaching.context import TeachingMaterial

    async with transaction() as conn:
        current = await job_service.locked_job(job, conn)
        if current["request"] != job["request"]:
            raise conflict("teaching_policy_changed", "课程任务配置已变化")
        course = await course_read.owned_course(job["user_id"], job["request"]["course_id"], conn=conn)
        await course_read.authorize_course(course, conn=conn)
        row = await fetch_one("SELECT * FROM learning_teaching_quality_runs WHERE task_id=%s AND owner_id=%s FOR UPDATE", (job["task_id"], job["user_id"]), conn=conn)
        if row is None:
            return None
        if row["policy_hash"] != policy_from_job(current).policy_hash or row["status"] in {"published", "revoked"}:
            raise conflict("course_quality_unavailable", "教学任务状态已变化")
        unfinished = await fetch_one("SELECT step_id FROM learning_teaching_agent_steps WHERE quality_run_id=%s AND status IN ('started','unknown') LIMIT 1", (row["quality_run_id"],), conn=conn)
        if unfinished:
            raise conflict("teaching_call_outcome_unknown", "上一教学步骤结果尚未确认，请显式重试任务")
        raw = load(row["checkpoint_json"], {}).get("material")
        if raw is None:
            raise conflict("course_quality_unavailable", "教学来源快照不可恢复，请显式重试任务")
        return TeachingMaterial(catalog=raw["catalog"], warnings=raw["warnings"], evidence={
            ref: DocumentEvidence.model_validate(item) for ref, item in raw["evidence"].items()
        })


async def _locked_run(job, conn):
    current = await job_service.locked_job(job, conn)
    if current["request"] != job["request"]:
        raise conflict("teaching_policy_changed", "课程任务配置已变化")
    from app.services import course_read

    course = await course_read.owned_course(job["user_id"], job["request"]["course_id"], conn=conn)
    await course_read.authorize_course(course, conn=conn)
    row = await fetch_one("SELECT * FROM learning_teaching_quality_runs WHERE task_id=%s AND owner_id=%s FOR UPDATE", (job["task_id"], job["user_id"]), conn=conn)
    if row is None or row["policy_hash"] != policy_from_job(current).policy_hash or row["status"] in {"published", "revoked"}:
        raise conflict("course_quality_unavailable", "教学任务状态已变化")
    return row


async def start_quality_run(job, agent_input, policy, *, conn=None):
    if conn is None:
        async with transaction() as tx:
            return await start_quality_run(job, agent_input, policy, conn=tx)
    current = await job_service.locked_job(job, conn)
    if current["request"] != job["request"] or policy_from_job(current) != policy:
        raise conflict("teaching_policy_changed", "课程任务配置已变化")
    from app.services import course_read

    course = await course_read.owned_course(job["user_id"], job["request"]["course_id"], conn=conn)
    await course_read.authorize_course(course, conn=conn)
    row = await fetch_one("SELECT * FROM learning_teaching_quality_runs WHERE task_id=%s FOR UPDATE", (job["task_id"],), conn=conn)
    skill_hash = job["request"].get("skill_hash")
    if not skill_hash:
        from app.teaching.prompts import teaching_skill

        skill_hash = teaching_skill()["hash"]
    if row is None:
        run_id = uid("tquality")
        await execute(
            "INSERT INTO learning_teaching_quality_runs(quality_run_id,task_id,owner_id,course_id,lesson_id,kind,"
            "criteria_revision,plan_hash,skill_hash,scope_fingerprint,policy_json,policy_hash,checkpoint_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (run_id, job["task_id"], job["user_id"], course["course_id"], job["request"].get("lesson_id"),
             agent_input.kind, agent_input.criteria_revision, agent_input.plan_hash, skill_hash,
             agent_input.scope_fingerprint, dump(policy), policy.policy_hash,
             dump({"material": _material_data(agent_input.material)})), conn=conn,
        )
        return {}
    expected = (job["user_id"], policy.policy_hash, agent_input.plan_hash, agent_input.criteria_revision, agent_input.scope_fingerprint, skill_hash)
    actual = (row["owner_id"], row["policy_hash"], row["plan_hash"], row["criteria_revision"], row["scope_fingerprint"], row["skill_hash"])
    if actual != expected or row["status"] in {"published", "revoked"}:
        raise conflict("course_quality_unavailable", "教学任务的冻结输入已变化")
    unfinished = await fetch_one("SELECT step_id FROM learning_teaching_agent_steps WHERE quality_run_id=%s AND status IN ('started','unknown') LIMIT 1", (row["quality_run_id"],), conn=conn)
    if unfinished:
        raise conflict("teaching_call_outcome_unknown", "上一教学步骤结果尚未确认，请显式重试任务")
    state = load(row["checkpoint_json"], {})
    if state.pop("material", None) != _material_data(agent_input.material):
        raise conflict("course_quality_unavailable", "教学来源快照已变化")
    state["candidate"] = load(row["candidate_json"])
    state["report"] = TeachingReviewReport.model_validate(load(row["report_json"])) if row["report_json"] else None
    state["deterministic_codes"] = tuple(state.get("deterministic_codes", ()))
    state["completed_slot"] = None
    return state


async def claim_agent_stage(job, stage_slot, role, *, candidate_hash, conn=None):
    if conn is None:
        async with transaction() as tx:
            return await claim_agent_stage(job, stage_slot, role, candidate_hash=candidate_hash, conn=tx)
    run = await _locked_run(job, conn)
    policy = policy_from_job(job)
    generation_role = "planner" if run["kind"] == "outline" else "teacher"
    if stage_slot not in SLOTS or role != ("reviewer" if stage_slot.startswith("review_") else generation_role):
        raise conflict("teaching_call_forbidden", "教学角色与步骤不匹配")
    existing = await fetch_one("SELECT * FROM learning_teaching_agent_steps WHERE quality_run_id=%s AND stage_slot=%s", (run["quality_run_id"], stage_slot), conn=conn)
    if existing:
        return {**existing, "claimed": False}
    if stage_slot.startswith("review_") and (not policy.review_enabled or not candidate_hash or candidate_hash != run["current_draft_hash"]):
        raise conflict("teaching_call_forbidden", "当前候选稿不可执行教学核对")
    if stage_slot == "review_recheck" and not run["repair_used"]:
        raise conflict("teaching_call_forbidden", "只有返修稿可以复核")
    if stage_slot == "repair" and run["repair_used"]:
        raise conflict("teaching_call_forbidden", "本任务返修次数已用完")
    if stage_slot == "repair":
        await execute("UPDATE learning_teaching_quality_runs SET repair_used=TRUE,generation_revision=2,updated_at=%s WHERE quality_run_id=%s", (now(), run["quality_run_id"]), conn=conn)
    revision = 2 if stage_slot == "repair" else run["generation_revision"]
    step_id = uid("tstep")
    await execute(
        "INSERT INTO learning_teaching_agent_steps(step_id,quality_run_id,task_id,owner_id,attempt,role,stage_slot,input_hash,draft_hash,generation_revision) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (step_id, run["quality_run_id"], job["task_id"], job["user_id"], job["attempt"], role, stage_slot,
         digest(dump({"request": job["request"], "stage_slot": stage_slot, "candidate_hash": candidate_hash})), candidate_hash, revision), conn=conn,
    )
    return {"step_id": step_id, "claimed": True, "status": "started"}


async def save_quality_checkpoint(job, state, *, conn=None):
    if conn is None:
        async with transaction() as tx:
            return await save_quality_checkpoint(job, state, conn=tx)
    run = await _locked_run(job, conn)
    candidate, report = state.get("candidate"), state.get("report")
    if candidate is not None and candidate["draft_hash"] != draft_hash(candidate["draft"]):
        raise conflict("course_draft_changed", "教学草案已变化")
    control = {key: state.get(key) for key in (
        "deterministic_codes", "generation_revision", "repair_used", "review_calls_started",
        "known_blocking", "terminal_reason", "reason_code", "trace",
    )}
    control["material"] = load(run["checkpoint_json"], {}).get("material")
    terminal = state.get("terminal_reason")
    status = "ready" if terminal == "completed" else "failed" if terminal else "running"
    await execute(
        "UPDATE learning_teaching_quality_runs SET candidate_json=%s,current_draft_hash=%s,report_json=%s,checkpoint_json=%s,"
        "generation_revision=%s,status=%s,reason_code=%s,updated_at=%s WHERE quality_run_id=%s",
        (dump(candidate) if candidate else None, candidate["draft_hash"] if candidate else None,
         dump(report) if report else None, dump(control), state["generation_revision"], status,
         state.get("reason_code"), now(), run["quality_run_id"]), conn=conn,
    )
    slot = state.get("completed_slot")
    if slot is None:
        return
    purpose = "course_teaching_review" if slot.startswith("review_") else "course_teaching_repair" if slot == "repair" else "course_" + run["kind"]
    provider = await fetch_one(
        "SELECT p.call_id FROM provider_calls p WHERE p.operation_id=%s AND p.owner_id=%s "
        "AND JSON_UNQUOTE(JSON_EXTRACT(p.usage_json,'$.purpose'))=%s "
        # Existing installations may use the database's default collation for
        # provider_calls. These opaque IDs require byte equality across schemas.
        "AND NOT EXISTS (SELECT 1 FROM learning_teaching_agent_steps s WHERE s.quality_run_id=%s AND CAST(s.provider_call_id AS BINARY)=CAST(p.call_id AS BINARY)) "
        "ORDER BY p.created_at DESC,p.call_id DESC LIMIT 1",
        (job["task_id"], job["user_id"], purpose, run["quality_run_id"]), conn=conn,
    )
    succeeded = report is not None and report.status != "unreviewed" if slot.startswith("review_") else candidate is not None
    await execute(
        "UPDATE learning_teaching_agent_steps SET status=%s,output_hash=%s,draft_hash=%s,report_json=%s,"
        "provider_call_id=%s,completed_at=%s WHERE quality_run_id=%s AND stage_slot=%s AND status='started'",
        ("completed" if succeeded else "failed", digest(dump(report)) if report else candidate["draft_hash"] if candidate else None,
         candidate["draft_hash"] if candidate else None, dump(report) if report else None,
         provider["call_id"] if provider else None, now(), run["quality_run_id"], slot), conn=conn,
    )


def artifact_binding(*, draft, evidence, skill_hash, course_id, lesson_id, content_version, criteria_revision):
    identities = []
    for ref, item in sorted(evidence.items()):
        identities.append({"source_ref": ref, **{key: item.get(key) for key in ("evidence_id", "document_version_id", "parse_artifact_id", "text_hash")}})
    return dict(draft_hash=draft_hash(draft), evidence=identities, skill_hash=skill_hash,
                course_id=course_id, lesson_id=lesson_id, content_version=content_version, criteria_revision=criteria_revision)


async def seal_quality_run(job, state, binding, *, conn):
    run = await _locked_run(job, conn)
    candidate = state.get("candidate")
    if state.get("terminal_reason") != "completed" or candidate is None or run["current_draft_hash"] != candidate["draft_hash"] or binding["draft_hash"] != candidate["draft_hash"]:
        raise conflict("course_quality_unavailable", "当前草案尚未完成教学流程")
    policy = policy_from_job(job)
    if policy.review_enabled:
        report = state.get("report")
        if report is None or report.status != "passed" or load(run["report_json"]) != report.model_dump(mode="json"):
            raise conflict("course_quality_unavailable", "当前草案未完成教学核对")
        require_review_binding(report, candidate, state["request"], skill_hash=run["skill_hash"], policy_hash=run["policy_hash"])
    await execute(
        "UPDATE learning_teaching_quality_runs SET status='published',candidate_json=NULL,checkpoint_json=JSON_REMOVE(checkpoint_json,'$.material'),artifact_json=%s,artifact_hash=%s,reason_code=%s,updated_at=%s WHERE quality_run_id=%s",
        (dump(binding), digest(dump(binding)), None if policy.review_enabled else "not_requested", now(), run["quality_run_id"]), conn=conn,
    )


def _summary(run, *, level, published=False, matches=True):
    if run is None:
        return TeachingQualitySummary(level=level, status="unreviewed", reason_code="legacy_content").model_dump(mode="json")
    report = TeachingReviewReport.model_validate(load(run["report_json"])) if run["report_json"] else None
    control = load(run["checkpoint_json"], {})
    bound = report is not None and (
        report.draft_hash, report.plan_hash, report.skill_hash, report.criteria_revision,
        report.scope_fingerprint, report.policy_hash,
    ) == (
        run["current_draft_hash"], run["plan_hash"], run["skill_hash"], run["criteria_revision"],
        run["scope_fingerprint"], run["policy_hash"],
    )
    reviewed = published and matches and bound and report.status == "passed"
    blocked = not published and (control.get("known_blocking") or report is not None and report.status == "needs_revision")
    warnings = []
    if reviewed and report.proposal:
        warnings = list(dict.fromkeys(WARNING_TEXT[finding.code] for finding in report.proposal.findings if finding.code in WARNING_TEXT))
    reason = None if reviewed else "content_changed" if not matches else run["reason_code"] or "review_pending"
    return TeachingQualitySummary(
        level=level, status="reviewed" if reviewed else "needs_revision" if blocked else "unreviewed",
        draft_hash=run["current_draft_hash"], artifact_hash=run["artifact_hash"] if published and matches else None,
        reason_code=reason, warnings=warnings,
    ).model_dump(mode="json")


async def _artifact_matches(run, course, row, *, conn=None):
    lesson_id = run["lesson_id"]
    raw = load(row["content_json" if lesson_id else "outline_json"], {})
    if not raw:
        return False
    if not lesson_id:
        lessons = await fetch_all("SELECT unit_json FROM learning_course_lessons WHERE course_id=%s AND owner_id=%s ORDER BY position", (course["course_id"], course["owner_id"]), conn=conn)
        raw = {**raw, "payload": {**raw["payload"], "units": [load(lesson["unit_json"]) for lesson in lessons]}}
    binding = artifact_binding(
        draft=raw, evidence=load(row["evidence_json"], {}), skill_hash=run["skill_hash"],
        course_id=course["course_id"], lesson_id=lesson_id, content_version=row["content_version"] if lesson_id else None,
        criteria_revision=course.get("criteria_revision", 1),
    )
    return digest(dump(binding)) == run["artifact_hash"]


async def quality_summary_for_course(owner, course_id, lesson_id=None, *, conn=None):
    from app.services import course_read

    course = await course_read.owned_course(owner, course_id, conn=conn)
    await course_read.authorize_course(course, conn=conn)
    row = await course_read.owned_lesson(owner, course_id, lesson_id, conn=conn) if lesson_id else course
    level = "lesson" if lesson_id else "outline"
    run = await fetch_one(
        "SELECT * FROM learning_teaching_quality_runs WHERE course_id=%s AND owner_id=%s AND lesson_id <=> %s AND status='published' ORDER BY created_at DESC,quality_run_id DESC LIMIT 1",
        (course_id, owner, lesson_id), conn=conn,
    )
    if run is None:
        return _summary(None, level=level)
    return _summary(run, level=level, published=True, matches=await _artifact_matches(run, course, row, conn=conn))


async def quality_summary_for_task(owner, task_id, *, conn=None):
    run = await fetch_one("SELECT * FROM learning_teaching_quality_runs WHERE task_id=%s AND owner_id=%s", (task_id, owner), conn=conn)
    if run is None:
        return None
    from app.services import course_read

    course = await course_read.owned_course(owner, run["course_id"], conn=conn)
    await course_read.authorize_course(course, conn=conn)
    matches = True
    if run["status"] == "published":
        row = await course_read.owned_lesson(owner, run["course_id"], run["lesson_id"], conn=conn) if run["lesson_id"] else course
        matches = await _artifact_matches(run, course, row, conn=conn)
    return _summary(run, level=run["kind"], published=run["status"] == "published", matches=matches)


async def mark_quality_terminated(job, *, conn):
    """Called by existing failure reconciliation while its task row is locked."""
    await execute(
        "UPDATE learning_teaching_quality_runs SET status='failed',reason_code=COALESCE(reason_code,%s),updated_at=%s WHERE task_id=%s AND owner_id=%s AND status IN ('running','ready')",
        (job.get("error_code") or "generation_stopped", now(), job["task_id"], job["user_id"]), conn=conn,
    )
    await execute("UPDATE learning_teaching_agent_steps SET status='unknown',completed_at=%s WHERE task_id=%s AND owner_id=%s AND attempt=%s AND status='started'", (now(), job["task_id"], job["user_id"], job["attempt"]), conn=conn)


async def purge_quality_content(owner, course_id, *, conn):
    await execute("UPDATE learning_teaching_agent_steps s JOIN learning_teaching_quality_runs r ON r.quality_run_id=s.quality_run_id SET s.report_json=NULL WHERE r.owner_id=%s AND r.course_id=%s", (owner, course_id), conn=conn)
    await execute("UPDATE learning_teaching_quality_runs SET candidate_json=NULL,report_json=NULL,checkpoint_json=JSON_REMOVE(checkpoint_json,'$.material'),status='revoked',reason_code='source_revoked',updated_at=%s WHERE owner_id=%s AND course_id=%s", (now(), owner, course_id), conn=conn)


async def purge_expired_quality_candidates(limit=100, *, owner_id=None, dry_run=False):
    limit = max(1, min(100, int(limit)))
    where = (
        "(r.candidate_json IS NOT NULL OR JSON_EXTRACT(r.checkpoint_json,'$.material') IS NOT NULL) "
        "AND t.status IN ('failed','cancelled') AND r.updated_at<UTC_TIMESTAMP(6)-INTERVAL 24 HOUR"
    )
    args = []
    if owner_id is not None:
        where += " AND r.owner_id=%s"
        args.append(owner_id)
    async with transaction() as conn:
        if dry_run:
            row = await fetch_one("SELECT COUNT(*) AS n FROM learning_teaching_quality_runs r JOIN quiz_tasks t ON t.task_id=r.task_id WHERE " + where, args, conn=conn)
            return row["n"]
        rows = await fetch_all(
            "SELECT r.quality_run_id FROM learning_teaching_quality_runs r JOIN quiz_tasks t ON t.task_id=r.task_id "
            "WHERE " + where + " ORDER BY r.updated_at LIMIT %s FOR UPDATE SKIP LOCKED",
            (*args, limit), conn=conn,
        )
        if not rows:
            return 0
        keys = [row["quality_run_id"] for row in rows]
        await execute("UPDATE learning_teaching_quality_runs SET candidate_json=NULL,checkpoint_json=JSON_REMOVE(checkpoint_json,'$.material') WHERE quality_run_id IN (" + ",".join(["%s"] * len(keys)) + ")", tuple(keys), conn=conn)
        return len(rows)
