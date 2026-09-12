"""Retention keeps business citations and settled costs, using real SQL/files/Chroma."""

import os
import time
from datetime import datetime, timedelta

import pytest

from app.core.db import execute, fetch_one
from app.core.values import digest, dump, load, now, uid
from app.rag.artifact_store import ArtifactStore, OwnerIndexStore


def stored(settings, key, value, *, age_days=0):
    store = ArtifactStore(settings.data_dir)
    path = store.resolve_key(store.put_json(key, value))
    if age_days:
        timestamp = time.time() - age_days * 86400
        os.utime(path, (timestamp, timestamp))
    return path


async def production_run(owner, settings):
    run_id = uid("rag")
    snapshot = f"snapshots/{digest(str(owner))}/kept.json"
    debug = f"rag/runs/{run_id}/1/debug.json"
    evidence = f"rag/runs/{run_id}/1/artifact.json"
    stored(settings, snapshot, {"text": "private source"}, age_days=40)
    stored(settings, debug, {"candidates": ["private debug"]}, age_days=40)
    stored(
        settings,
        evidence,
        {"evidence_pack": {"evidence": [{"snapshot_artifact_key": snapshot}]}},
        age_days=40,
    )
    await execute(
        "INSERT INTO rag_runs(run_id,owner_id,mode,namespace,pipeline_hash,manifest_json,status,evidence_artifact_key,debug_artifact_key,debug_expires_at) "
        "VALUES(%s,%s,'production','production',%s,%s,'completed',%s,%s,%s)",
        (
            run_id,
            owner,
            "a" * 64,
            dump({"scope": {"documents": []}}),
            evidence,
            debug,
            now() - timedelta(days=1),
        ),
    )
    return run_id, evidence, debug, snapshot


async def evaluation_run(owner, settings, *, private_release_claim=False):
    dataset_id, run_id, result_id = uid("dataset"), uid("eval"), uid("result")
    sample = {
        "sample_id": "sample-one",
        "case_type": "quiz",
        "family_ids": ["family-one"],
        "split": "dev",
        "tags": ["synthetic"],
        "query": "private query",
        "gold": {"answer": "private gold"},
    }
    manifest = {
        "dataset_hash": "b" * 64,
        "pipeline_config_hash": "c" * 64,
        "source_scopes": {},
        "release": private_release_claim,
        "private_extra": "private text",
    }
    key = f"evaluation/artifacts/{run_id}/1/prediction.json"
    stored(
        settings,
        key,
        {"questions": [{"stem": "private stem"}], "usage": {"cost_cny": 1.25}},
        age_days=100,
    )
    metrics = {
        "fixture_accuracy": {"value": 0.5, "denominator": 2, "status": "ok"},
        "total_cost_cny": {"value": 1.25, "denominator": 1, "status": "ok"},
    }
    await execute(
        "INSERT INTO eval_datasets(dataset_id,version,owner_id,name,status,manifest_json,samples_json,checksum) VALUES(%s,1,%s,'Retention fixture','frozen',%s,%s,%s)",
        (dataset_id, owner, dump({"sources": []}), dump([sample]), "b" * 64),
    )
    await execute(
        "INSERT INTO eval_runs(run_id,owner_id,dataset_id,dataset_version,pipeline_id,manifest_json,request_hash,idempotency_key,status,repeat_count,max_cost_cny,deadline_at,created_at) VALUES(%s,%s,%s,1,'dense-v1',%s,%s,%s,'completed',1,2,%s,%s)",
        (
            run_id,
            owner,
            dataset_id,
            dump(manifest),
            digest(run_id),
            run_id,
            now() - timedelta(days=99),
            now() - timedelta(days=100),
        ),
    )
    await execute(
        "INSERT INTO eval_results(result_id,run_id,sample_id,repeat_index,case_type,sample_json,status,prediction_status,artifact_json,artifact_key,metrics_json,review_json) VALUES(%s,%s,'sample-one',0,'quiz',%s,'completed','completed',%s,%s,%s,%s)",
        (
            result_id,
            run_id,
            dump(sample),
            dump({"questions": [{"stem": "private stem"}]}),
            key,
            dump(metrics),
            dump({"comment": "private comment"}),
        ),
    )
    return run_id, result_id, key, metrics


@pytest.mark.asyncio
async def test_default_dry_run_preserves_files_then_apply_only_expires_debug(
    learner, platform_settings
):
    from app.services import budget_service, maintenance

    owner = learner[1]["user"]["id"]
    run_id, evidence, debug, snapshot = await production_run(owner, platform_settings)
    operation = uid("uncertain")
    await budget_service.reserve_budget(
        operation, "cny", 2, [(f"retention-test:{owner}", 5)]
    )
    await budget_service.settle_budget(operation, "cny", unknown=True)
    await execute(
        "UPDATE auth_sessions SET expires_at=%s WHERE user_id=%s",
        (now() - timedelta(days=1), owner),
    )
    report = await maintenance.run_maintenance(owner_id=owner)
    assert report["dry_run"] is True
    store = ArtifactStore(platform_settings.data_dir)
    assert store.resolve_key(debug).exists()
    assert (
        await fetch_one(
            "SELECT debug_artifact_key FROM rag_runs WHERE run_id=%s", (run_id,)
        )
    )["debug_artifact_key"] == debug
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    assert not store.resolve_key(debug).exists()
    assert store.resolve_key(evidence).exists() and store.resolve_key(snapshot).exists()
    assert (
        await fetch_one(
            "SELECT evidence_artifact_key FROM rag_runs WHERE run_id=%s", (run_id,)
        )
    )["evidence_artifact_key"] == evidence
    assert (
        await fetch_one(
            "SELECT status,actual FROM budget_reservations WHERE operation_id=%s",
            (operation,),
        )
    )["status"] == "unknown"
    assert (
        await fetch_one(
            "SELECT COUNT(*) AS n FROM auth_sessions WHERE user_id=%s", (owner,)
        )
    )["n"] == 0
    assert (await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,)))[
        "total_xp"
    ] == 0


@pytest.mark.asyncio
async def test_evaluation_expiry_ignores_manifest_release_claim_and_preserves_metrics(
    learner, platform_settings
):
    from app.services import maintenance

    owner = learner[1]["user"]["id"]
    run_id, result_id, key, metrics = await evaluation_run(
        owner, platform_settings, private_release_claim=True
    )
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    row = await fetch_one("SELECT * FROM eval_results WHERE result_id=%s", (result_id,))
    assert row["artifact_json"] is None and row["artifact_key"] is None
    assert load(row["metrics_json"]) == metrics
    sample = load(row["sample_json"])
    assert sample["family_ids"] == ["family-one"] and sample["split"] == "dev"
    assert "private" not in dump(sample) and "private" not in (row["review_json"] or "")
    manifest = load(
        (
            await fetch_one(
                "SELECT manifest_json FROM eval_runs WHERE run_id=%s", (run_id,)
            )
        )["manifest_json"]
    )
    assert (
        manifest["raw_artifacts_status"] == "expired"
        and manifest["reproducible"] is False
    )
    assert "private" not in dump(manifest)
    assert not ArtifactStore(platform_settings.data_dir).resolve_key(key).exists()


@pytest.mark.asyncio
async def test_long_retention_requires_explicit_operator_receipt_and_apply(
    learner, platform_settings
):
    from app.services import maintenance

    owner = learner[1]["user"]["id"]
    run_id, result_id, key, _ = await evaluation_run(owner, platform_settings)
    arguments = dict(
        run_id=run_id,
        operator="fixture-operator",
        reason="Reviewed public benchmark",
        basis="public_release",
        authorization_sha256="d" * 64,
    )
    await maintenance.hold_evaluation_run(**arguments)
    assert not await fetch_one(
        "SELECT run_id FROM eval_retention_holds WHERE run_id=%s", (run_id,)
    )
    await maintenance.hold_evaluation_run(**arguments, apply=True)
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    assert (
        await fetch_one(
            "SELECT artifact_json FROM eval_results WHERE result_id=%s", (result_id,)
        )
    )["artifact_json"] is not None
    assert ArtifactStore(platform_settings.data_dir).resolve_key(key).exists()


@pytest.mark.asyncio
async def test_maintenance_refuses_a_second_live_chroma_owner(
    learner, platform_settings
):
    from app.rag.errors import OwnerRequired
    from app.services import maintenance

    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner"):
        with pytest.raises(OwnerRequired):
            await maintenance.run_maintenance(owner_id=learner[1]["user"]["id"])


@pytest.mark.asyncio
async def test_committed_expiry_retries_file_cleanup_after_io_failure(
    learner, platform_settings, monkeypatch
):
    from pathlib import Path
    from app.services import maintenance

    owner = learner[1]["user"]["id"]
    run_id, _, debug, _ = await production_run(owner, platform_settings)
    target = ArtifactStore(platform_settings.data_dir).resolve_key(debug)
    original = Path.unlink

    def denied(path, *args, **kwargs):
        if path == target:
            raise PermissionError("fixture locked file")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", denied)
    report = await maintenance.run_maintenance(
        apply=True, operator="fixture", owner_id=owner
    )
    assert report["errors"] and target.exists()
    assert (
        await fetch_one(
            "SELECT debug_artifact_key FROM rag_runs WHERE run_id=%s", (run_id,)
        )
    )["debug_artifact_key"] is None
    monkeypatch.setattr(Path, "unlink", original)
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    assert not target.exists()


@pytest.mark.asyncio
async def test_orphans_observe_grace_period_and_preserve_sql_assets(
    learner, platform_settings
):
    from app.services import maintenance

    owner = learner[1]["user"]["id"]
    orphan = stored(platform_settings, "raw/orphan.txt", {"text": "orphan"}, age_days=2)
    young = stored(platform_settings, "raw/young.txt", {"text": "upload in progress"})
    kept = stored(
        platform_settings, "assets/kept.png", {"image": "fixture"}, age_days=2
    )
    await execute(
        "INSERT INTO user_assets(asset_id,owner_id,storage_key,content_type) VALUES(%s,%s,'assets/kept.png','image/png')",
        (uid("asset"), owner),
    )
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        await maintenance.sweep_orphans(store, apply=True, operator="fixture")
    assert not orphan.exists() and young.exists() and kept.exists()


@pytest.mark.asyncio
async def test_candidate_cleanup_keeps_all_published_old_builds(
    learner, platform_settings
):
    from app.rag.contracts import ActorContext
    from app.rag.engine import RagEngine
    from app.services import job_service, maintenance, source_service
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding

    api, session = learner
    owner = session["user"]["id"]
    platform_settings.dashscope_embedding_model = "fixture-vector-v1"
    platform_settings.embedding_dimensions = 3
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(
                store, FixtureEmbedding(), reauthorize=source_service.reauthorize_scope
            )
        )
        response = await api.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "retained.txt",
                    "合成资料：光合作用需要光。".encode(),
                    "text/plain",
                )
            },
        )
        document = response.json()["data"]
        await worker.run_once(task_id=document["task_id"])
        first = await fetch_one(
            "SELECT manifest_json FROM kb_index_builds WHERE doc_id=%s AND status='ready'",
            (document["doc_id"],),
        )
        replacement = await source_service.reindex_document(
            ActorContext(owner_id=owner), document["doc_id"], "legacy-char-v1"
        )
        await worker.run_once(task_id=replacement["task_id"])
        pending = await source_service.reindex_document(
            ActorContext(owner_id=owner), document["doc_id"], "legacy-char-v1"
        )
        job = await job_service.claim_job(
            "fixture-candidate", task_id=pending["task_id"]
        )
        candidate = await store.build(
            await source_service.build_request(job), FixtureEmbedding()
        )
        await job_service.fail_job(job, "fixture-abandoned")
        for file in store.resolve_key("rag/projections").rglob("*"):
            if file.is_file():
                old = time.time() - 2 * 86400
                os.utime(file, (old, old))
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        assert not store.projection_exists(candidate)
        from app.rag.contracts import BuildResult

        original = BuildResult.model_validate(load(first["manifest_json"]))
        assert store.projection_exists(original)
        store.read_build(original.to_source_manifest(1))


@pytest.mark.asyncio
async def test_debug_pointer_alias_never_deletes_business_evidence(
    learner, platform_settings
):
    from app.services import maintenance

    owner = learner[1]["user"]["id"]
    run_id, evidence, _, snapshot = await production_run(owner, platform_settings)
    await execute(
        "UPDATE rag_runs SET debug_artifact_key=%s WHERE run_id=%s", (evidence, run_id)
    )
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    store = ArtifactStore(platform_settings.data_dir)
    assert store.resolve_key(evidence).exists() and store.resolve_key(snapshot).exists()
    row = await fetch_one(
        "SELECT debug_artifact_key,evidence_artifact_key FROM rag_runs WHERE run_id=%s",
        (run_id,),
    )
    assert (
        row["debug_artifact_key"] is None and row["evidence_artifact_key"] == evidence
    )


@pytest.mark.asyncio
async def test_old_evaluation_with_active_scoring_lease_keeps_raw_until_lease_ends(
    learner, platform_settings
):
    from app.services import maintenance

    owner = learner[1]["user"]["id"]
    run_id, result_id, key, _ = await evaluation_run(owner, platform_settings)
    await execute(
        "UPDATE eval_results SET scoring_expires_at=%s WHERE result_id=%s",
        (now() + timedelta(minutes=2), result_id),
    )
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    assert ArtifactStore(platform_settings.data_dir).resolve_key(key).exists()
    assert (
        await fetch_one(
            "SELECT artifact_json FROM eval_results WHERE result_id=%s", (result_id,)
        )
    )["artifact_json"] is not None
    await execute(
        "UPDATE eval_results SET scoring_expires_at=%s WHERE result_id=%s",
        (now() - timedelta(seconds=1), result_id),
    )
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    assert not ArtifactStore(platform_settings.data_dir).resolve_key(key).exists()


@pytest.mark.asyncio
async def test_dataset_revocation_overrides_hold_without_waiting_for_retention_date(
    learner, platform_settings
):
    from app.rag.contracts import ActorContext
    from app.services import eval_dataset_service, maintenance

    owner = learner[1]["user"]["id"]
    run_id, result_id, key, metrics = await evaluation_run(owner, platform_settings)
    await execute("UPDATE eval_runs SET created_at=%s WHERE run_id=%s", (now(), run_id))
    await maintenance.hold_evaluation_run(
        run_id=run_id,
        operator="fixture",
        reason="Reviewed release",
        basis="public_release",
        authorization_sha256="a" * 64,
        apply=True,
    )
    run = await fetch_one(
        "SELECT dataset_id,dataset_version FROM eval_runs WHERE run_id=%s", (run_id,)
    )
    await eval_dataset_service.revoke_dataset(
        ActorContext(owner_id=owner), run["dataset_id"], run["dataset_version"]
    )
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    result = await fetch_one(
        "SELECT artifact_json,metrics_json FROM eval_results WHERE result_id=%s",
        (result_id,),
    )
    assert result["artifact_json"] is None and load(result["metrics_json"]) == metrics
    assert not ArtifactStore(platform_settings.data_dir).resolve_key(key).exists()


@pytest.mark.asyncio
async def test_failed_delete_is_swept_again_even_after_a_successful_previous_cleanup(
    learner, platform_settings
):
    from app.rag.contracts import BuildResult
    from app.rag.engine import RagEngine
    from app.services import job_service, maintenance, source_service
    from app.workers.rag_owner import OwnerWorker
    from tests.rag.helpers import FixtureEmbedding

    api, session = learner
    owner = session["user"]["id"]
    platform_settings.dashscope_embedding_model = "fixture-vector-v1"
    platform_settings.embedding_dimensions = 3
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        worker = OwnerWorker(
            RagEngine(
                store, FixtureEmbedding(), reauthorize=source_service.reauthorize_scope
            )
        )
        response = await api.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "deleted.txt",
                    "合成测试资料：光合作用需要光。".encode(),
                    "text/plain",
                )
            },
        )
        document = response.json()["data"]
        await worker.run_once(task_id=document["task_id"])
        row = await fetch_one(
            "SELECT manifest_json FROM kb_index_builds WHERE doc_id=%s AND status='ready'",
            (document["doc_id"],),
        )
        built = BuildResult.model_validate(load(row["manifest_json"]))
        raw = await fetch_one(
            "SELECT storage_key FROM kb_document_versions WHERE doc_id=%s",
            (document["doc_id"],),
        )
        deleted = (
            await api.delete(f"/api/v1/knowledge/documents/{document['doc_id']}")
        ).json()["data"]
        job = await job_service.claim_job("fixture-cleaner", task_id=deleted["task_id"])
        await job_service.fail_job(job, "fixture-interruption")
        assert store.projection_exists(built)
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    store = ArtifactStore(platform_settings.data_dir)
    assert not store.resolve_key(raw["storage_key"]).exists()
    assert not store.resolve_key(built.projection_key).exists()
    assert not store.resolve_key(built.canonical_artifact_key).exists()
    # Recreate a late raw residue after an earlier successful sweep. The durable
    # tombstone must still win, even though its prior audit says completed.
    stored(
        platform_settings, raw["storage_key"], {"text": "late revoked private source"}
    )
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    assert not store.resolve_key(raw["storage_key"]).exists()
    assert (await fetch_one("SELECT total_xp FROM users WHERE id=%s", (owner,)))[
        "total_xp"
    ] == 0


@pytest.mark.asyncio
async def test_unreadable_retained_evidence_fails_closed_for_snapshot_sweep(
    learner, platform_settings
):
    from app.services import maintenance

    owner = learner[1]["user"]["id"]
    _, evidence, _, snapshot = await production_run(owner, platform_settings)
    path = ArtifactStore(platform_settings.data_dir).resolve_key(evidence)
    path.write_bytes(b'{"evidence_pack":')
    uncited = stored(
        platform_settings,
        "snapshots/unknown-origin.json",
        {"text": "citation cannot be verified"},
        age_days=40,
    )
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        result = await maintenance.sweep_orphans(store, apply=True, operator="fixture")
    assert result["warnings"]
    assert (
        uncited.exists()
        and ArtifactStore(platform_settings.data_dir).resolve_key(snapshot).exists()
    )


@pytest.mark.asyncio
async def test_pending_build_keeps_its_canonical_and_attempt_files(
    learner, platform_settings
):
    from app.services import job_service, maintenance, source_service
    from tests.rag.helpers import FixtureEmbedding

    api, _ = learner
    platform_settings.dashscope_embedding_model = "fixture-vector-v1"
    platform_settings.embedding_dimensions = 3
    with OwnerIndexStore(platform_settings.data_dir, process_role="rag_owner") as store:
        response = await api.post(
            "/api/v1/knowledge/documents",
            files={
                "file": (
                    "pending.txt",
                    "合成资料：光合作用需要光。".encode(),
                    "text/plain",
                )
            },
        )
        task_id = response.json()["data"]["task_id"]
        job = await job_service.claim_job("fixture-interrupted", task_id=task_id)
        candidate = await store.build(
            await source_service.build_request(job), FixtureEmbedding()
        )
        await execute(
            "UPDATE quiz_tasks SET status='pending',lease_expires_at=NULL WHERE task_id=%s",
            (task_id,),
        )
        # Files from a recoverable task are not orphans just because they are old.
        for path in store.root.rglob("*"):
            if path.is_file():
                old = time.time() - 2 * 86400
                os.utime(path, (old, old))
        await maintenance.sweep_orphans(store, apply=True, operator="fixture")
        assert store.projection_exists(candidate)
        assert store.resolve_key(candidate.canonical_artifact_key).exists()
        store.read_build(candidate.to_source_manifest(1))


@pytest.mark.asyncio
async def test_operator_receipt_is_required_and_cannot_restore_expired_content(
    learner, platform_settings
):
    from app.core.errors import AppError
    from app.services import maintenance

    owner = learner[1]["user"]["id"]
    run_id, _, _, _ = await evaluation_run(owner, platform_settings)
    arguments = dict(
        run_id=run_id,
        operator="fixture",
        reason="Reviewed release",
        basis="public_release",
        authorization_sha256="a" * 64,
        apply=True,
    )
    with pytest.raises(AppError) as error:
        await maintenance.hold_evaluation_run(
            **{**arguments, "authorization_sha256": "user-supplied-release-flag"}
        )
    assert error.value.code == "retention_authorization_required"
    await maintenance.run_maintenance(apply=True, operator="fixture", owner_id=owner)
    with pytest.raises(AppError) as error:
        await maintenance.hold_evaluation_run(**arguments)
    assert error.value.code == "retention_run_ineligible"


@pytest.mark.parametrize(
    "age_days,status,dataset_status,held,expired,expected",
    [
        (0, "cancelled", "revoked", True, False, True),
        (100, "completed", "frozen", True, False, False),
        (100, "completed", "frozen", False, False, True),
        (89, "completed", "frozen", False, False, False),
        (100, "running", "frozen", False, False, False),
        (100, "completed", "frozen", False, True, False),
    ],
)
def test_retention_due_decision(
    age_days, status, dataset_status, held, expired, expected
):
    from app.services import maintenance

    stamp = datetime(2030, 1, 1)
    row = {
        "created_at": stamp - timedelta(days=age_days),
        "status": status,
        "manifest_json": dump({"raw_artifacts_status": "expired"} if expired else {}),
    }
    assert (
        maintenance._evaluation_due(
            row, dataset_status=dataset_status, held=held, stamp=stamp
        )
        is expected
    )


@pytest.mark.asyncio
async def test_retained_candidate_registry_includes_canonical_dependency(tmp_path):
    from app.services import maintenance
    from tests.rag.helpers import FixtureEmbedding, request_for

    with OwnerIndexStore(tmp_path / "artifacts", process_role="rag_owner") as store:
        candidate = await store.build(request_for(tmp_path), FixtureEmbedding())
        intent = load(
            store.resolve_key(candidate.projection_key + "/attempt.json").read_bytes()
        )
        references = maintenance.References()
        maintenance._protect_candidate(store, intent, references)
        assert references.protects(candidate.canonical_artifact_key)
        assert references.protects(candidate.projection_key + "/docstore.json")
        assert not references.protects("sources/another-owner/unrelated.json")
