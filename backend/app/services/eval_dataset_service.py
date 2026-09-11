"""Versioned labels with server-recorded review and source revocation gates."""

import copy

from rag_eval.datasets import validate_dataset

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import conflict, not_found
from app.core.values import digest, dump, iso, load, now, uid
from app.rag.contracts import BuildResult, ResolvedScope
from app.services.source_service import artifacts, reauthorize_scope


async def dataset_row(owner, dataset_id, version, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM eval_datasets WHERE dataset_id=%s AND version=%s AND owner_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (dataset_id, version, owner),
        conn=conn,
    )
    if not row:
        raise not_found()
    return row


def view(row, *, include_samples=True):
    from collections import Counter

    samples = load(row["samples_json"]) if row["status"] != "revoked" else []
    return {
        **{
            key: row[key]
            for key in (
                "dataset_id",
                "version",
                "name",
                "status",
                "revision",
                "checksum",
            )
        },
        "manifest": load(row["manifest_json"]),
        "samples": samples if include_samples else [],
        "sample_count": len(samples),
        "split_counts": dict(Counter(s.get("split", "unspecified") for s in samples)),
    }


def clean_import(manifest, samples):
    manifest = copy.deepcopy(manifest)
    samples = copy.deepcopy(samples)
    manifest["state"] = "draft"
    manifest["release_gold_status"] = "draft"
    for field in (
        "frozen_by",
        "frozen_at",
        "review_summary",
        "formal_gold_eligible",
        "source_similarity_audit",
    ):
        manifest.pop(field, None)
    for source in manifest.get("sources", []):
        for field in (
            "storage_key",
            "artifact_key",
            "canonical_text",
            "canonical_text_path",
        ):
            source.pop(field, None)
    for sample in samples:
        sample.setdefault("annotation", {})["review_records"] = []
        sample["annotation"]["human_review_status"] = "pending"
        for source in sample.get("source_refs", []):
            for field in (
                "storage_key",
                "artifact_key",
                "canonical_text",
                "canonical_text_path",
            ):
                source.pop(field, None)
    return manifest, samples


async def hydrate(owner, manifest, samples, *, conn=None):
    manifest = copy.deepcopy(manifest)
    samples = copy.deepcopy(samples)
    registered = manifest.get("sources", [])
    cache = {}
    for source in [
        *registered,
        *[r for s in samples for r in s.get("source_refs", [])],
    ]:
        version = source.get("source_version_id", source.get("document_version_id"))
        key = (source.get("doc_id"), version, source.get("parse_artifact_id"))
        if key not in cache:
            row = await fetch_one(
                "SELECT b.*,d.authorization_revision,d.purpose,d.deleted_at FROM kb_index_builds b JOIN kb_documents d ON d.doc_id=b.doc_id AND d.user_id=b.owner_id WHERE b.doc_id=%s AND b.version_id=%s AND b.parse_artifact_id=%s AND b.owner_id=%s AND b.status='ready' ORDER BY b.created_at DESC LIMIT 1",
                (*key, owner),
                conn=conn,
            )
            if not row or row["deleted_at"] or row["purpose"] != "evaluation":
                raise not_found()
            build = BuildResult.model_validate(load(row["manifest_json"]))
            await reauthorize_scope(
                ResolvedScope(
                    owner_id=owner,
                    namespace=build.namespace,
                    documents=[build.to_source_manifest(row["authorization_revision"])],
                ),
                conn=conn,
            )
            canonical = artifacts().load_canonical(build.canonical_artifact_key)
            cache[key] = (canonical, build, row["authorization_revision"])
        canonical, build, _auth_revision = cache[key]
        if (
            source.get("canonical_text_hash") != canonical.canonical_text_hash
            or source.get("source_sha256") != canonical.source_sha256
        ):
            raise conflict("source_identity_mismatch", "来源校验和与已授权资料不一致")
        source["canonical_text"] = canonical.text
        source["source_version_id"] = canonical.document_version_id
        source.setdefault("license", "private_owner_authorized")
        source["authorization_status"] = "authorized"
    return manifest, samples, cache


async def validated(owner, manifest, samples, *, frozen=False, conn=None):
    hydrated, hydrated_samples, cache = await hydrate(
        owner, manifest, samples, conn=conn
    )
    report = validate_dataset(
        hydrated,
        hydrated_samples,
        require_frozen=frozen,
        allow_single_review_freeze=True,
    )
    if not report["valid"]:
        codes = ", ".join(e["code"] for e in report["errors"][:4])
        raise conflict("dataset_validation_failed", "数据集校验未通过：" + codes)
    return report, cache


async def store_draft(
    actor,
    name,
    manifest,
    samples,
    *,
    dataset_id=None,
    expected_parent_version=None,
    conn=None,
):
    """Store a validated new version. Internal callers may preserve trusted prior reviews."""
    if conn is None:
        async with transaction() as tx:
            return await store_draft(
                actor,
                name,
                manifest,
                samples,
                dataset_id=dataset_id,
                expected_parent_version=expected_parent_version,
                conn=tx,
            )
    manifest = copy.deepcopy(manifest)
    samples = copy.deepcopy(samples)
    report, _ = await validated(actor.owner_id, manifest, samples, conn=conn)
    if dataset_id:
        existing = await fetch_one(
            "SELECT version,status FROM eval_datasets WHERE dataset_id=%s AND owner_id=%s ORDER BY version DESC LIMIT 1 FOR UPDATE",
            (dataset_id, actor.owner_id),
            conn=conn,
        )
        if not existing:
            raise not_found()
        if (
            existing["status"] == "revoked"
            or expected_parent_version is not None
            and existing["version"] != expected_parent_version
        ):
            raise conflict(
                "dataset_parent_changed", "目标数据集已更新或撤销，请刷新后重试"
            )
        version = existing["version"] + 1
    else:
        dataset_id = uid("dataset")
        version = 1
    manifest.update(
        schema_version="1",
        dataset_id=dataset_id,
        version=version,
        revision=1,
        state="draft",
        release_gold_status="draft",
    )
    await execute(
        "INSERT INTO eval_datasets(dataset_id,version,owner_id,name,manifest_json,samples_json) VALUES(%s,%s,%s,%s,%s,%s)",
        (dataset_id, version, actor.owner_id, name, dump(manifest), dump(samples)),
        conn=conn,
    )
    result = view(await dataset_row(actor.owner_id, dataset_id, version, conn=conn))
    result["validation"] = report
    return result


async def create_dataset(actor, body):
    manifest, samples = clean_import(body.manifest, body.samples)
    return await store_draft(
        actor, body.name, manifest, samples, dataset_id=body.dataset_id
    )


async def get_dataset(owner, dataset_id, version):
    row = await dataset_row(owner, dataset_id, version)
    if row["status"] != "revoked":
        await hydrate(owner, load(row["manifest_json"]), load(row["samples_json"]))
    return view(row)


async def list_datasets(owner):
    rows = await fetch_all(
        "SELECT * FROM eval_datasets WHERE owner_id=%s ORDER BY created_at DESC",
        (owner,),
    )
    return {"items": [view(r, include_samples=False) for r in rows], "total": len(rows)}


async def patch_dataset(actor, dataset_id, version, body):
    async with transaction() as conn:
        preview = await dataset_row(actor.owner_id, dataset_id, version, conn=conn)
        if preview["status"] in ("frozen", "revoked"):
            raise conflict("immutable_dataset", "请创建新版本后修改")
        manifest, samples = clean_import(
            body.manifest or load(preview["manifest_json"]),
            body.samples if body.samples is not None else load(preview["samples_json"]),
        )
        report, _ = await validated(actor.owner_id, manifest, samples, conn=conn)
        row = await dataset_row(
            actor.owner_id, dataset_id, version, conn=conn, lock=True
        )
        if row["status"] in ("frozen", "revoked"):
            raise conflict("immutable_dataset", "请创建新版本后修改")
        if row["revision"] != body.revision:
            raise conflict()
        manifest.update(
            dataset_id=dataset_id, version=version, revision=row["revision"] + 1
        )
        await execute(
            "UPDATE eval_datasets SET name=%s,manifest_json=%s,samples_json=%s,status='draft',revision=revision+1 WHERE dataset_id=%s AND version=%s",
            (
                body.name or row["name"],
                dump(manifest),
                dump(samples),
                dataset_id,
                version,
            ),
            conn=conn,
        )
    result = view(await dataset_row(actor.owner_id, dataset_id, version))
    result["validation"] = report
    return result


async def review_sample(actor, dataset_id, version, sample_id, body):
    async with transaction() as conn:
        preview = await dataset_row(actor.owner_id, dataset_id, version, conn=conn)
        await hydrate(
            actor.owner_id,
            load(preview["manifest_json"]),
            load(preview["samples_json"]),
            conn=conn,
        )
        row = await dataset_row(
            actor.owner_id, dataset_id, version, conn=conn, lock=True
        )
        if row["status"] in ("frozen", "revoked"):
            raise conflict("immutable_dataset", "请创建新版本后复核")
        if row["revision"] != body.expected_revision:
            raise conflict()
        samples = load(row["samples_json"])
        sample = next((s for s in samples if s["sample_id"] == sample_id), None)
        if sample is None:
            raise not_found()
        annotation = sample.setdefault("annotation", {})
        record = {
            "reviewer_id": str(actor.owner_id),
            "reviewed_at": iso(now()),
            "decision": body.verdict,
            "provenance": "human",
            "independent": True,
            "comment": body.comment,
        }
        annotation.setdefault("review_records", []).append(record)
        annotation["human_review_status"] = (
            "approved" if body.verdict == "approved" else "needs_changes"
        )
        if body.verdict != "approved":
            annotation["review_records"] = [record]
        await execute(
            "UPDATE eval_datasets SET samples_json=%s,revision=revision+1 WHERE dataset_id=%s AND version=%s",
            (dump(samples), dataset_id, version),
            conn=conn,
        )
    return view(await dataset_row(actor.owner_id, dataset_id, version))


async def freeze_dataset(actor, dataset_id, version, expected_revision, checklist=None):
    async with transaction() as conn:
        preview = await dataset_row(actor.owner_id, dataset_id, version, conn=conn)
        if preview["status"] == "frozen":
            await hydrate(
                actor.owner_id,
                load(preview["manifest_json"]),
                load(preview["samples_json"]),
                conn=conn,
            )
            current = await dataset_row(
                actor.owner_id, dataset_id, version, conn=conn, lock=True
            )
            if (
                current["status"] != "frozen"
                or current["checksum"] != preview["checksum"]
            ):
                raise conflict("dataset_changed", "数据集状态已发生变化")
            return view(current)
        if preview["status"] == "revoked" or preview["revision"] != expected_revision:
            raise conflict()
        manifest = load(preview["manifest_json"])
        samples = load(preview["samples_json"])
        if checklist is not None:
            manifest.setdefault("review", {})["checklist"] = checklist
        manifest["state"] = "frozen"
        report, _ = await validated(
            actor.owner_id, manifest, samples, frozen=True, conn=conn
        )
        row = await dataset_row(
            actor.owner_id, dataset_id, version, conn=conn, lock=True
        )
        if row["status"] == "revoked" or row["revision"] != expected_revision:
            raise conflict()
        manifest["release_gold_status"] = report["release_gold_status"]
        manifest["review_summary"] = report["review"]
        manifest["formal_gold_eligible"] = report["formal_gold_eligible"]
        manifest["source_similarity_audit"] = report["source_similarity_audit"]
        manifest["sample_clusters"] = {
            sid: cluster for cluster, ids in report["clusters"].items() for sid in ids
        }
        manifest["frozen_by"] = actor.owner_id
        manifest["frozen_at"] = iso(now())
        checksum = digest(dump({"manifest": manifest, "samples": samples}))
        key = f"evaluation/datasets/{digest(dataset_id)[:16]}-{version}.json"
        artifacts().put_json(key, {"manifest": manifest, "samples": samples})
        await execute(
            "UPDATE eval_datasets SET status='frozen',revision=revision+1,manifest_json=%s,checksum=%s,artifact_key=%s WHERE dataset_id=%s AND version=%s",
            (dump(manifest), checksum, key, dataset_id, version),
            conn=conn,
        )
    result = view(await dataset_row(actor.owner_id, dataset_id, version))
    result["validation"] = report
    return result


async def revoke_dataset(actor, dataset_id, version):
    async with transaction() as conn:
        row = await dataset_row(
            actor.owner_id, dataset_id, version, conn=conn, lock=True
        )
        await execute(
            "UPDATE eval_datasets SET status='revoked',samples_json=JSON_ARRAY(),artifact_key=NULL,revision=revision+1 WHERE dataset_id=%s AND version=%s",
            (dataset_id, version),
            conn=conn,
        )
        await execute(
            "UPDATE eval_runs SET status='cancelled',stop_reason='dataset_revoked' WHERE dataset_id=%s AND dataset_version=%s",
            (dataset_id, version),
            conn=conn,
        )
    if row["artifact_key"]:
        artifacts().resolve_key(row["artifact_key"]).unlink(missing_ok=True)
    return {"dataset_id": dataset_id, "version": version, "status": "revoked"}
