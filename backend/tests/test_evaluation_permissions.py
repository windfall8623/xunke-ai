"""Database-free regression tests for system evaluation authorization boundaries."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core import db
from app.core.errors import AppError, not_found
from app.core.values import digest, dump
from app.models.evaluation import RunCreate
from app.models.feedback import FeedbackPromote
from app.rag.contracts import ActorContext, PipelineConfig, ResolvedScope
from app.services import evaluation_scoring as scoring
from app.services import evaluation_service as runs
from app.services import feedback_service as feedback
from app.services import source_service as sources


@pytest.fixture
def authorization(monkeypatch):
    state = SimpleNamespace(role="admin", reads=[])

    async def current_role(sql, args=(), *, conn=None):
        assert sql == "SELECT role FROM users WHERE id=%s" + (
            " FOR SHARE" if conn is not None else ""
        )
        assert args == (7,)
        state.reads.append(conn)
        return {"role": state.role} if state.role is not None else None

    monkeypatch.setattr(db, "fetch_one", current_role)
    return state


def fake_transaction(monkeypatch, module, authorization, *, demote=False):
    conn = object()

    @asynccontextmanager
    async def transaction():
        if demote:
            authorization.role = "evaluator"
        yield conn

    monkeypatch.setattr(module, "transaction", transaction)
    return conn


def assert_denied(caught):
    assert (caught.value.status, caught.value.code) == (
        403, "system_model_admin_required"
    )


def run_body():
    return RunCreate(
        dataset_id="dataset", dataset_version=1, pipeline_id="dense-v1", max_cost_cny=2
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["learner", "evaluator", None])
@pytest.mark.parametrize("operation", ["create", "resume", "upload", "reindex", "copy", "promote"])
async def test_stale_admin_cannot_start_or_replay_evaluation(
    monkeypatch, authorization, role, operation
):
    authorization.role = role
    actor = ActorContext(owner_id=7, role="admin")
    untouched = AsyncMock(side_effect=AssertionError("Denied request reached work"))
    monkeypatch.setattr(runs, "fetch_one", untouched)
    monkeypatch.setattr(runs, "authorized_run", untouched)
    monkeypatch.setattr(sources, "read_upload", untouched)
    monkeypatch.setattr(sources, "owned_document", untouched)
    monkeypatch.setattr(sources, "reauthorize_scope", untouched)
    monkeypatch.setattr(feedback, "owned_feedback", untouched)
    operations = {
        "create": lambda: runs.create_run(actor, run_body(), "existing-key"),
        "resume": lambda: runs.resume_run(7, "already-running"),
        "upload": lambda: sources.upload_document(actor, None, purpose="evaluation"),
        "reindex": lambda: sources.reindex_document(actor, "doc", "legacy-char-v1", purpose="evaluation"),
        "copy": lambda: sources.copy_for_evaluation(actor, None, "existing-copy"),
        "promote": lambda: feedback.promote_feedback(actor, "promoted", None),
    }
    with pytest.raises(AppError) as caught:
        await operations[operation]()
    assert_denied(caught)
    assert authorization.reads == [None]
    untouched.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_run_rechecks_admin_in_scheduling_transaction(monkeypatch, authorization):
    actor, body = ActorContext(owner_id=7, role="admin"), run_body()
    manifest, samples = {"state": "frozen", "sources": []}, []
    dataset = {
        "status": "frozen", "manifest_json": dump(manifest), "samples_json": dump(samples),
        "checksum": digest(dump({"manifest": manifest, "samples": samples})),
    }
    monkeypatch.setattr(runs, "fetch_one", AsyncMock(return_value=None))
    monkeypatch.setattr(runs, "pipeline_config", lambda _: PipelineConfig())
    monkeypatch.setattr(runs, "code_fingerprint", lambda: "fixture-code")
    monkeypatch.setattr(runs, "runtime_dependencies", lambda: {})
    monkeypatch.setattr(runs, "provider_manifest", lambda: {})
    monkeypatch.setattr(runs.datasets, "dataset_row", AsyncMock(return_value=dataset))
    monkeypatch.setattr(runs.datasets, "validated", AsyncMock(return_value=({
        "clusters": {}, "review": {"human_reviewed_count": 0},
        "release_gold_status": "provisional_single_review", "formal_gold_eligible": False,
    }, {})))
    writes = AsyncMock(side_effect=AssertionError("Demoted actor scheduled work"))
    monkeypatch.setattr(runs, "execute", writes)
    monkeypatch.setattr(runs.job_service, "enqueue_job", writes)
    conn = fake_transaction(monkeypatch, runs, authorization, demote=True)
    with pytest.raises(AppError) as caught:
        await runs.create_run(actor, body, "new-key")
    assert_denied(caught)
    assert authorization.reads == [None, conn]
    writes.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_run_rechecks_admin_before_job_locks(monkeypatch, authorization):
    monkeypatch.setattr(runs, "authorized_run", AsyncMock(return_value={
        "status": "cancelled", "manifest_json": "{}"
    }))
    touched = AsyncMock(side_effect=AssertionError("Demoted actor resumed work"))
    monkeypatch.setattr(runs, "fetch_all", touched)
    monkeypatch.setattr(runs, "execute", touched)
    conn = fake_transaction(monkeypatch, runs, authorization, demote=True)
    with pytest.raises(AppError) as caught:
        await runs.resume_run(7, "cancelled-run")
    assert_denied(caught)
    assert authorization.reads == [None, conn]
    touched.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["upload", "reindex", "copy"])
async def test_source_ingest_rechecks_admin_before_transaction_writes(
    monkeypatch, authorization, tmp_path, operation
):
    from app.rag.artifact_store import ArtifactStore
    from tests.rag.test_artifact_pipeline import context_and_scope

    actor = ActorContext(owner_id=7, role="admin")
    conn = fake_transaction(monkeypatch, sources, authorization, demote=True)
    monkeypatch.setattr(sources, "read_upload", AsyncMock(return_value=("fixture.txt", "txt", b"fixture")))
    monkeypatch.setattr(sources, "artifacts", lambda: ArtifactStore(tmp_path))
    monkeypatch.setattr(sources, "fetch_one", AsyncMock(return_value={"id": 7}))
    monkeypatch.setattr(sources, "_discard_uncommitted_raw", AsyncMock())
    untouched = AsyncMock(side_effect=AssertionError("Demoted actor touched sources"))
    monkeypatch.setattr(sources, "owned_document", untouched)
    monkeypatch.setattr(sources, "reauthorize_scope", untouched)
    monkeypatch.setattr(sources, "execute", untouched)
    monkeypatch.setattr(sources.job_service, "enqueue_job", untouched)
    source = context_and_scope()[3].documents[0].model_copy(update={"namespace": "production"})
    operations = {
        "upload": lambda: sources.upload_document(actor, None, purpose="evaluation"),
        "reindex": lambda: sources.reindex_document(actor, "doc", "legacy-char-v1", purpose="evaluation"),
        "copy": lambda: sources.copy_for_evaluation(actor, source, "copy-key"),
    }
    with pytest.raises(AppError) as caught:
        await operations[operation]()
    assert_denied(caught)
    assert authorization.reads == [None, conn]
    untouched.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,purpose", [("evaluation", "evaluation"), ("production", "evaluation"), ("evaluation", "production")])
async def test_source_publication_rechecks_current_job_owner_role(
    monkeypatch, authorization, mode, purpose
):
    authorization.role = "evaluator"
    conn = object()
    current = {"user_id": 7, "mode": mode, "request": {"purpose": purpose, "doc_id": "doc"}}
    candidate = SimpleNamespace(doc_id="doc", index_build_id="build")

    async def complete(job, payload, *, publisher):
        await publisher(current, payload, conn)

    monkeypatch.setattr(sources.job_service, "complete_job", complete)
    untouched = AsyncMock(side_effect=AssertionError("Demoted actor published an index"))
    monkeypatch.setattr(sources, "owned_document", untouched)
    monkeypatch.setattr(sources, "execute", untouched)
    with pytest.raises(AppError) as caught:
        await sources.publish_build({"user_id": 999}, candidate)
    assert_denied(caught)
    assert authorization.reads == [conn]
    untouched.assert_not_awaited()


@pytest.mark.asyncio
async def test_feedback_promotion_rechecks_admin_before_reserving_identity(monkeypatch, authorization):
    actor = ActorContext(owner_id=7, role="admin")
    body = FeedbackPromote(expected_revision=1, name="Candidate", redacted_request="Facts")
    monkeypatch.setattr(feedback, "owned_feedback", AsyncMock(return_value={
        "allow_evaluation": True, "status": "approved", "review_json": dump({"revision": 1})
    }))
    monkeypatch.setattr(feedback, "_quiz_source_context", AsyncMock(return_value=(
        {}, ResolvedScope(owner_id=7, namespace="production")
    )))
    untouched = AsyncMock(side_effect=AssertionError("Demoted actor promoted feedback"))
    monkeypatch.setattr(feedback, "execute", untouched)
    monkeypatch.setattr(feedback.sources, "copy_for_evaluation", untouched)
    conn = fake_transaction(monkeypatch, feedback, authorization, demote=True)
    with pytest.raises(AppError) as caught:
        await feedback.promote_feedback(actor, "feedback", body)
    assert_denied(caught)
    assert authorization.reads == [None, conn]
    untouched.assert_not_awaited()


@pytest.mark.asyncio
async def test_scoring_claim_skips_demoted_owner_without_leasing_or_hydrating(monkeypatch, authorization):
    authorization.role = "evaluator"
    conn = fake_transaction(monkeypatch, scoring, authorization)
    monkeypatch.setattr(scoring, "fetch_one", AsyncMock(return_value={"owner_id": 7}))
    monkeypatch.setattr(scoring, "fetch_all", AsyncMock(return_value=[{"result_id": "result"}]))
    writes = AsyncMock()
    monkeypatch.setattr(scoring, "execute", writes)
    hydrate = AsyncMock(side_effect=AssertionError("Demoted scorer read private data"))
    monkeypatch.setattr(scoring.eval_dataset_service, "hydrate", hydrate)
    assert await scoring.claim_scoring("worker") is None
    assert authorization.reads == [conn]
    assert len(writes.await_args_list) == 2
    assert writes.await_args_list[-1].args[1] == ("system_model_admin_required", "result")
    assert all("scoring_lease_token=%s" not in call.args[0] for call in writes.await_args_list)
    hydrate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["heartbeat", "complete", "fail", "reserve"])
async def test_scoring_active_lease_cannot_authorize_after_demotion(
    monkeypatch, authorization, operation
):
    authorization.role = "evaluator"
    conn = fake_transaction(monkeypatch, scoring, authorization)
    monkeypatch.setattr(scoring, "fetch_one", AsyncMock(return_value={"owner_id": 7}))
    writes = AsyncMock(side_effect=AssertionError("Demoted scorer published or reserved"))
    monkeypatch.setattr(scoring, "execute", writes)
    monkeypatch.setattr(scoring, "_journal", writes)
    operations = {
        "heartbeat": lambda: scoring.heartbeat_scoring("result", "lease", 1),
        "complete": lambda: scoring.complete_scoring("result", "lease", 1, {
            "metric": {"status": "ok", "value": 1, "denominator": 1}
        }),
        "fail": lambda: scoring.fail_scoring("result", "lease", 1, "scoring_error"),
        "reserve": lambda: scoring.journal_call("result", "lease", 1, {
            "call_id": "judge", "stage": "judge", "status": "reserved", "reserved_cost_cny": 0.5
        }),
    }
    with pytest.raises(AppError) as caught:
        await operations[operation]()
    assert_denied(caught)
    assert authorization.reads == [conn]
    writes.assert_not_awaited()


@pytest.mark.asyncio
async def test_demoted_scoring_owner_can_settle_only_an_existing_reserved_receipt(monkeypatch, authorization):
    authorization.role = "evaluator"
    conn = fake_transaction(monkeypatch, scoring, authorization)
    old = {"owner_id": 7, "usage_json": dump({"lease_fingerprint": digest("lease")})}
    run = {"owner_id": 7, "run_id": "run"}
    fetch = AsyncMock(side_effect=[old, run])
    monkeypatch.setattr(scoring, "fetch_one", fetch)
    settled = {"accepted": True, "status": "completed"}
    journal = AsyncMock(return_value=settled)
    monkeypatch.setattr(scoring, "_journal", journal)
    call = {"call_id": "judge", "stage": "judge", "status": "completed", "cost_cny": 0.1, "cost_status": "estimated"}
    assert await scoring.journal_call("result", "lease", 1, call) == settled
    assert authorization.reads == []
    journal.assert_awaited_once_with({"result_id": "result", "scoring_attempt": 1}, run, call, conn)
    assert fetch.await_args_list[-1].args[1] == ("result", 7)
    fetch.side_effect = [None]
    with pytest.raises(AppError) as caught:
        await scoring.journal_call("result", "lease", 1, call)
    assert caught.value.code == "stale_scoring_lease"
    assert journal.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["run", "source", "feedback"])
async def test_admin_still_cannot_access_another_owners_resource(monkeypatch, authorization, operation):
    actor = ActorContext(owner_id=7, role="admin")
    conn = fake_transaction(monkeypatch, sources, authorization)
    reads = AsyncMock(return_value=None)
    for module in (runs, sources, feedback):
        monkeypatch.setattr(module, "fetch_one", reads)
    with pytest.raises(AppError) as caught:
        if operation == "run":
            await runs.resume_run(7, "foreign")
        elif operation == "source":
            await sources.reindex_document(actor, "foreign", "legacy-char-v1", purpose="evaluation")
        else:
            await feedback.promote_feedback(actor, "foreign", None)
    assert caught.value.status == 404
    assert reads.await_args.args[1][:2] == ("foreign", 7)
    if operation == "source":
        assert authorization.reads == [None, conn]


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["learner", "evaluator", "admin"])
@pytest.mark.parametrize("foreign", [False, True])
@pytest.mark.parametrize("operation", ["context", "review"])
async def test_manual_practice_review_allows_evaluator_admin_but_keeps_owner_gate(
    monkeypatch, authorization, role, foreign, operation
):
    from app.services import practice_grading_service as grading
    from app.services import practice_view_service as views

    actor = ActorContext(owner_id=7, role=role)
    module = views if operation == "context" else grading
    fake_transaction(monkeypatch, module, authorization)
    ownership = AsyncMock(return_value=None if foreign else {"practice_id": "practice"})
    if operation == "context":
        monkeypatch.setattr(views, "fetch_one", ownership)
        proceed = AsyncMock(side_effect=AppError(409, "owned_review", "Authorized review"))
        monkeypatch.setattr(views.practice_service, "authorize_practice", proceed)
    else:
        if foreign:
            ownership.side_effect = not_found()
        monkeypatch.setattr(grading, "_attempt_preview", ownership)
        proceed = AsyncMock(side_effect=AppError(409, "owned_review", "Authorized review"))
        monkeypatch.setattr(grading, "locked_grading_state", proceed)
    with pytest.raises(AppError) as caught:
        if operation == "context":
            await views.get_practice_review_context(actor, "attempt")
        else:
            await grading._review_once(actor, "attempt", None, "key", "hash")
    expected = "not_found" if foreign else "evaluator_required" if role == "learner" else "owned_review"
    assert caught.value.code == expected
    assert proceed.await_count == int(not foreign and role in {"evaluator", "admin"})
    assert authorization.reads == []
