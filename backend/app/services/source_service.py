"""SQL owns source authorization and publication; Chroma is a disposable projection."""

import io
import json
import zipfile
from pathlib import Path

from app.core.config import get_settings
from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load, uid
from app.rag.artifact_store import ArtifactStore
from app.rag.contracts import (
    BuildRequest,
    BuildResult,
    IndexProfile,
    ResolvedScope,
    SourceInput,
    SourceManifest,
)
from app.rag.errors import ScopeRevoked, SourceUnavailable
from app.services import job_service


def artifacts():
    return ArtifactStore(get_settings().data_dir)


async def _discard_uncommitted_raw(owner, version_id, path):
    # A lost COMMIT acknowledgement is not proof of rollback. Serialize with
    # deterministic evaluation-copy retries before testing the durable reference.
    try:
        async with transaction() as conn:
            await fetch_one(
                "SELECT id FROM users WHERE id=%s FOR UPDATE", (owner,), conn=conn
            )
            reference = await fetch_one(
                "SELECT version_id FROM kb_document_versions WHERE version_id=%s",
                (version_id,),
                conn=conn,
            )
            if reference is None:
                path.unlink(missing_ok=True)
    except BaseException:
        # If database state is unknown, retain the bytes for the orphan sweep.
        pass


def profile(profile_id="legacy-char-v1"):
    profile_id = "structure-token-v1" if profile_id == "structure-v1" else profile_id
    if profile_id not in ("legacy-char-v1", "structure-token-v1"):
        raise AppError(422, "invalid_index_profile", "索引配置不存在")
    s = get_settings()
    return IndexProfile(
        profile_id=profile_id,
        embedding_model=s.dashscope_embedding_model,
        embedding_dimensions=s.embedding_dimensions,
        chunker="structure_token"
        if profile_id == "structure-token-v1"
        else "recursive_character",
    )


async def owned_document(owner, doc_id, *, purpose="production", conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM kb_documents WHERE doc_id=%s AND user_id=%s AND purpose=%s AND deleted_at IS NULL"
        + (" FOR UPDATE" if lock else ""),
        (doc_id, owner, purpose),
        conn=conn,
    )
    if not row:
        raise not_found()
    return row


async def document_view(row, task_id=None):
    result = {
        k: row.get(k)
        for k in (
            "doc_id",
            "file_name",
            "file_type",
            "file_size",
            "status",
            "purpose",
            "active_version_id",
            "active_build_id",
            "document_revision",
            "chunk_count",
            "error_code",
            "error_message",
        )
    }
    result.update(
        {
            "sections": [],
            "section_catalog_revision": None,
            "task_id": task_id,
            "created_at": iso(row.get("created_at")),
        }
    )
    if row["active_build_id"]:
        build = await fetch_one(
            "SELECT canonical_artifact_key,parse_artifact_id FROM kb_index_builds WHERE build_id=%s AND owner_id=%s AND status='ready'",
            (row["active_build_id"], row["user_id"]),
        )
        if build and build["canonical_artifact_key"]:
            try:
                canonical = artifacts().load_canonical(build["canonical_artifact_key"])
            except SourceUnavailable:
                result.update(
                    status="needs_reupload",
                    error_code="source_artifact_unavailable",
                    error_message="资料索引文件不可用，请重新上传或重建索引",
                )
            else:
                result["section_catalog_revision"] = canonical.parse_artifact_id
                result["sections"] = [
                    {"section_id": s.section_id, "title": s.title}
                    for s in canonical.sections
                ]
    if not row["active_version_id"] and row["namespace"] == "legacy":
        result.update(
            status="needs_reupload",
            error_code="legacy_source_unavailable",
            error_message="旧资料需重新上传以建立可追溯索引",
        )
    return result


async def list_documents(owner, purpose="production"):
    rows = await fetch_all(
        "SELECT * FROM kb_documents WHERE user_id=%s AND purpose=%s AND deleted_at IS NULL ORDER BY created_at DESC",
        (owner, purpose),
    )
    return {"items": [await document_view(r) for r in rows], "total": len(rows)}


async def read_upload(file):
    name = (file.filename or "document").replace("\\", "/").split("/")[-1][:255]
    ext = Path(name).suffix.lower().lstrip(".")
    if ext not in ("pdf", "docx", "md", "txt"):
        raise AppError(422, "unsupported_file", "支持 PDF、DOCX、Markdown 和 TXT")
    content = bytearray()
    limit = get_settings().kb_max_file_size_mb * 1024 * 1024
    while part := await file.read(min(65536, limit + 1 - len(content))):
        content.extend(part)
        if len(content) > limit:
            raise AppError(413, "file_too_large", "文件超过大小限制")
    raw = bytes(content)
    if not raw:
        raise AppError(422, "empty_file", "文件为空")
    try:
        if ext == "pdf" and not raw.startswith(b"%PDF-"):
            raise ValueError("PDF signature")
        if ext == "docx":
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                if (
                    "word/document.xml" not in archive.namelist()
                    or sum(i.file_size for i in archive.infolist()) > 50 * 1024 * 1024
                ):
                    raise ValueError("DOCX content")
        if ext in ("txt", "md"):
            text = raw.decode("utf-8-sig")
            if "\x00" in text or not text.strip():
                raise ValueError("UTF-8 text")
    except (ValueError, UnicodeError, zipfile.BadZipFile) as exc:
        raise AppError(
            422, "invalid_file_content", "文件内容与格式不符，文本请使用 UTF-8 编码"
        ) from exc
    return name, ext, raw


async def upload_document(actor, file, *, purpose="production", doc_id=None):
    name, ext, raw = await read_upload(file)
    new_doc = doc_id is None
    doc_id = doc_id or uid("doc")
    version = uid("ver")
    build_id = uid("build")
    namespace = (
        "production" if purpose == "production" else f"evaluation:{actor.owner_id}"
    )
    key = f"raw/{version}.{ext}"
    path = artifacts().resolve_key(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    try:
        async with transaction() as conn:
            await fetch_one(
                "SELECT id FROM users WHERE id=%s FOR UPDATE",
                (actor.owner_id,),
                conn=conn,
            )
            if new_doc:
                count = await fetch_one(
                    "SELECT COUNT(*) AS n FROM kb_documents WHERE user_id=%s AND purpose=%s AND deleted_at IS NULL",
                    (actor.owner_id, purpose),
                    conn=conn,
                )
                maximum = (
                    get_settings().kb_max_documents_per_user
                    if purpose == "production"
                    else 300
                )
                if count["n"] >= maximum:
                    raise AppError(409, "document_limit", "资料数量已达到上限")
                revision = 1
                await execute(
                    "INSERT INTO kb_documents(doc_id,user_id,file_name,file_type,file_size,purpose,namespace) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (doc_id, actor.owner_id, name, ext, len(raw), purpose, namespace),
                    conn=conn,
                )
            else:
                current = await owned_document(
                    actor.owner_id, doc_id, purpose=purpose, conn=conn, lock=True
                )
                namespace = (
                    namespace
                    if current["namespace"] == "legacy"
                    else current["namespace"]
                )
                revision = current["document_revision"] + 1
                await execute(
                    "UPDATE kb_documents SET file_name=%s,file_type=%s,file_size=%s,status='processing',document_revision=%s,namespace=%s,error_code=NULL,error_message=NULL WHERE doc_id=%s",
                    (name, ext, len(raw), revision, namespace, doc_id),
                    conn=conn,
                )
            await execute(
                "INSERT INTO kb_document_versions(version_id,doc_id,owner_id,source_sha256,storage_key,file_type,file_bytes) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (version, doc_id, actor.owner_id, digest(raw), key, ext, len(raw)),
                conn=conn,
            )
            await execute(
                "INSERT INTO kb_index_builds(build_id,doc_id,owner_id,version_id,namespace,index_profile_id,expected_document_revision) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (
                    build_id,
                    doc_id,
                    actor.owner_id,
                    version,
                    namespace,
                    "legacy-char-v1",
                    revision,
                ),
                conn=conn,
            )
            job = await job_service.enqueue_job(
                actor.owner_id,
                "ingest",
                {
                    "doc_id": doc_id,
                    "version_id": version,
                    "build_id": build_id,
                    "document_revision": revision,
                    "purpose": purpose,
                },
                f"ingest:{build_id}",
                mode="evaluation" if purpose == "evaluation" else "production",
                conn=conn,
            )
        return await document_view(
            await owned_document(actor.owner_id, doc_id, purpose=purpose),
            job["task_id"],
        )
    except BaseException:
        await _discard_uncommitted_raw(actor.owner_id, version, path)
        raise


async def reindex_document(actor, doc_id, index_profile_id, *, purpose="production"):
    index_profile_id = profile(index_profile_id).profile_id
    async with transaction() as conn:
        row = await owned_document(
            actor.owner_id, doc_id, purpose=purpose, conn=conn, lock=True
        )
        if not row["active_version_id"]:
            raise conflict("source_not_ready", "请先完成资料导入")
        build_id = uid("build")
        revision = row["document_revision"] + 1
        await execute(
            "UPDATE kb_documents SET document_revision=%s,status='processing',error_code=NULL WHERE doc_id=%s",
            (revision, doc_id),
            conn=conn,
        )
        await execute(
            "INSERT INTO kb_index_builds(build_id,doc_id,owner_id,version_id,namespace,index_profile_id,expected_document_revision) VALUES(%s,%s,%s,%s,%s,%s,%s)",
            (
                build_id,
                doc_id,
                actor.owner_id,
                row["active_version_id"],
                row["namespace"],
                index_profile_id,
                revision,
            ),
            conn=conn,
        )
        job = await job_service.enqueue_job(
            actor.owner_id,
            "ingest",
            {
                "doc_id": doc_id,
                "version_id": row["active_version_id"],
                "build_id": build_id,
                "document_revision": revision,
                "purpose": purpose,
            },
            f"ingest:{build_id}",
            mode="evaluation" if purpose == "evaluation" else "production",
            conn=conn,
        )
    return await document_view(
        await owned_document(actor.owner_id, doc_id, purpose=purpose), job["task_id"]
    )


async def build_request(job):
    request = job["request"]
    row = await owned_document(
        job["user_id"], request["doc_id"], purpose=request["purpose"]
    )
    if row["document_revision"] != request["document_revision"]:
        raise conflict("source_changed", "资料已有更新的构建任务")
    version = await fetch_one(
        "SELECT * FROM kb_document_versions WHERE version_id=%s AND doc_id=%s AND owner_id=%s",
        (request["version_id"], row["doc_id"], job["user_id"]),
    )
    build = await fetch_one(
        "SELECT * FROM kb_index_builds WHERE build_id=%s AND owner_id=%s",
        (request["build_id"], job["user_id"]),
    )
    return BuildRequest(
        index_build_id=request["build_id"],
        attempt_id=f"attempt_{job['attempt']}_{digest(job['lease_token'])[:16]}",
        source=SourceInput(
            owner_id=job["user_id"],
            namespace=row["namespace"],
            doc_id=row["doc_id"],
            document_version_id=version["version_id"],
            file_path=str(artifacts().resolve_key(version["storage_key"])),
            file_type=version["file_type"],
            source_sha256=version["source_sha256"],
            title=row["file_name"],
        ),
        profile=profile(build["index_profile_id"]),
        expected_document_revision=request["document_revision"],
        lease_token=job["lease_token"],
    )


async def publish_build(job, result):
    async def publisher(current, payload, conn):
        request = current["request"]
        row = await owned_document(
            current["user_id"],
            request["doc_id"],
            purpose=request["purpose"],
            conn=conn,
            lock=True,
        )
        if (
            row["document_revision"] != result.expected_document_revision
            or result.index_build_id != request["build_id"]
        ):
            raise conflict("source_changed", "资料已有更新的构建任务")
        if (
            result.owner_id,
            result.doc_id,
            result.namespace,
            result.document_version_id,
        ) != (row["user_id"], row["doc_id"], row["namespace"], request["version_id"]):
            raise ScopeRevoked()
        await execute(
            "UPDATE kb_index_builds SET status='ready',parse_artifact_id=%s,canonical_artifact_key=%s,index_profile_hash=%s,manifest_json=%s,published_attempt_id=%s,node_count=%s,lease_token=%s WHERE build_id=%s AND status='building'",
            (
                result.parse_artifact_id,
                result.canonical_artifact_key,
                result.index_profile_hash,
                dump(result),
                result.attempt_id,
                result.node_count,
                current["lease_token"],
                result.index_build_id,
            ),
            conn=conn,
        )
        for node in sorted(result.nodes, key=lambda n: not n.is_parent):
            await execute(
                "INSERT INTO kb_nodes(node_id,build_id,attempt_id,doc_id,owner_id,version_id,parent_id,text_hash,storage_key,locator_json) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    node.node_id,
                    result.index_build_id,
                    result.attempt_id,
                    row["doc_id"],
                    row["user_id"],
                    result.document_version_id,
                    node.parent_id,
                    node.evidence.text_hash,
                    result.canonical_artifact_key,
                    dump(node.evidence.locator),
                ),
                conn=conn,
            )
        count = await execute(
            "UPDATE kb_documents SET active_version_id=%s,active_build_id=%s,status='ready',chunk_count=%s,error_code=NULL,error_message=NULL WHERE doc_id=%s AND document_revision=%s AND deleted_at IS NULL",
            (
                result.document_version_id,
                result.index_build_id,
                result.node_count,
                row["doc_id"],
                result.expected_document_revision,
            ),
            conn=conn,
        )
        if count != 1:
            raise conflict("source_changed", "资料已发生变化")

    await job_service.complete_job(
        job,
        {"doc_id": result.doc_id, "build_id": result.index_build_id},
        publisher=publisher,
    )


async def resolve_scope(
    actor, requested, *, purpose="production", index_profile_id=None
):
    manifests = []
    namespace = None
    for selected in requested.documents:
        row = await owned_document(actor.owner_id, selected.doc_id, purpose=purpose)
        build = (
            await fetch_one(
                "SELECT * FROM kb_index_builds WHERE build_id=%s AND owner_id=%s AND status='ready'",
                (row["active_build_id"], actor.owner_id),
            )
            if row["active_build_id"]
            else None
        )
        if not build:
            raise conflict("source_not_ready", "资料尚未就绪，请稍后重试")
        result = BuildResult.model_validate(load(build["manifest_json"]))
        if index_profile_id and result.profile.profile_id != index_profile_id:
            raise conflict("index_profile_mismatch", "所选资料需要重建兼容索引")
        canonical = artifacts().load_canonical(result.canonical_artifact_key)
        if selected.section_ids:
            if selected.section_catalog_revision != canonical.parse_artifact_id:
                raise conflict("section_catalog_changed", "章节目录已更新，请刷新资料")
            if not set(selected.section_ids) <= {
                s.section_id for s in canonical.sections
            }:
                raise not_found()
        manifests.append(
            result.to_source_manifest(
                row["authorization_revision"], selected.section_ids
            )
        )
        namespace = row["namespace"]
    return ResolvedScope(
        owner_id=actor.owner_id,
        namespace=namespace
        or (
            "production" if purpose == "production" else f"evaluation:{actor.owner_id}"
        ),
        documents=manifests,
    )


async def reauthorize_scope(scope, *, conn=None):
    scope = ResolvedScope.model_validate(scope)
    for source in sorted(scope.documents, key=lambda item: item.doc_id):
        preview = await fetch_one(
            "SELECT lineage_json FROM kb_documents WHERE doc_id=%s AND user_id=%s",
            (source.doc_id, scope.owner_id),
            conn=conn,
        )
        if preview and preview["lineage_json"]:
            origin = load(preview["lineage_json"])
            origin_owner = origin.get("owner_id", scope.owner_id)
            if origin_owner != scope.owner_id:
                raise ScopeRevoked("资料副本不属于当前账号")
            valid = await fetch_one(
                "SELECT authorization_revision FROM kb_documents WHERE doc_id=%s AND user_id=%s AND deleted_at IS NULL"
                + (" FOR SHARE" if conn else ""),
                (origin["doc_id"], origin_owner),
                conn=conn,
            )
            if (
                not valid
                or valid["authorization_revision"] != origin["authorization_revision"]
            ):
                raise ScopeRevoked("原始资料授权已撤销")
        row = await fetch_one(
            "SELECT * FROM kb_documents WHERE doc_id=%s AND user_id=%s AND namespace=%s AND deleted_at IS NULL"
            + (" FOR SHARE" if conn else ""),
            (source.doc_id, scope.owner_id, scope.namespace),
            conn=conn,
        )
        if not row or row["authorization_revision"] != source.authorization_revision:
            raise ScopeRevoked("资料已撤销或删除")
        build = await fetch_one(
            "SELECT manifest_json,published_attempt_id FROM kb_index_builds WHERE build_id=%s AND owner_id=%s AND doc_id=%s AND version_id=%s AND status='ready'",
            (
                source.index_build_id,
                scope.owner_id,
                source.doc_id,
                source.document_version_id,
            ),
            conn=conn,
        )
        if not build or build["published_attempt_id"] != source.attempt_id:
            raise ScopeRevoked("索引版本不可用")
        saved = BuildResult.model_validate(load(build["manifest_json"]))
        if (
            saved.parse_artifact_id,
            saved.canonical_text_hash,
            saved.source_sha256,
            saved.projection_key,
            saved.canonical_artifact_key,
        ) != (
            source.parse_artifact_id,
            source.canonical_text_hash,
            source.source_sha256,
            source.projection_key,
            source.canonical_artifact_key,
        ):
            raise ScopeRevoked("来源版本不匹配")
    return scope


async def revoke_document(actor, doc_id, *, purpose="production"):
    async with transaction() as conn:
        row = await owned_document(
            actor.owner_id, doc_id, purpose=purpose, conn=conn, lock=True
        )
        affected = {doc_id: row}
        copies = await fetch_all(
            "SELECT * FROM kb_documents WHERE user_id=%s AND lineage_json IS NOT NULL AND deleted_at IS NULL ORDER BY doc_id",
            (actor.owner_id,),
            conn=conn,
        )
        while True:
            descendants = [
                copy
                for copy in copies
                if copy["doc_id"] not in affected
                and load(copy["lineage_json"]).get("doc_id") in affected
            ]
            if not descendants:
                break
            affected.update({copy["doc_id"]: copy for copy in descendants})
        for removed_id, removed in affected.items():
            await execute(
                "UPDATE kb_documents SET deleted_at=UTC_TIMESTAMP(6),status='deleted',document_revision=document_revision+1,authorization_revision=authorization_revision+1 WHERE doc_id=%s AND deleted_at IS NULL",
                (removed_id,),
                conn=conn,
            )
            cleanup = await job_service.enqueue_job(
                actor.owner_id,
                "delete",
                {
                    "doc_id": removed_id,
                    "purpose": removed["purpose"],
                    "namespace": removed["namespace"],
                },
                f"delete:{removed_id}",
                mode="evaluation"
                if removed["purpose"] == "evaluation"
                else "production",
                conn=conn,
            )
            if removed_id == doc_id:
                deletion = cleanup
        # Revoke frozen snapshots immediately. No export can bypass the source gate.
        datasets = await fetch_all(
            "SELECT dataset_id,version,samples_json FROM eval_datasets WHERE owner_id=%s AND status<>'revoked'",
            (actor.owner_id,),
            conn=conn,
        )
        for dataset in datasets:
            if any(
                ref.get("doc_id") in affected
                for sample in load(dataset["samples_json"], [])
                for ref in sample.get("source_refs", [])
            ):
                await execute(
                    "UPDATE eval_datasets SET status='revoked',revision=revision+1 WHERE dataset_id=%s AND version=%s",
                    (dataset["dataset_id"], dataset["version"]),
                    conn=conn,
                )
    # Release source locks before touching jobs. Publication rechecks tombstones
    # under its lease, so cancellation cannot create a job/source lock cycle.
    jobs = await fetch_all(
        "SELECT task_id,kind,request_json,scope_json FROM quiz_tasks WHERE user_id=%s AND status IN ('pending','running') AND kind<>'delete'",
        (actor.owner_id,),
    )
    for job in jobs:
        request = load(job["request_json"], {})
        scope = load(job["scope_json"], {})
        if request.get("doc_id") in affected or any(
            d["doc_id"] in affected for d in scope.get("documents", [])
        ):
            await job_service.cancel_job(actor.owner_id, job["task_id"])
    return {"doc_id": doc_id, "status": "deleted", "task_id": deletion["task_id"]}


async def copy_for_evaluation(actor, source_manifest, idempotency_key):
    """Copy the pinned original into this owner's evaluation namespace once.

    This is called after explicit feedback consent and reviewer authorization.
    It copies source bytes, never promotes generated answers to gold labels.
    """
    source = SourceManifest.model_validate(source_manifest)
    if (
        "evaluator" not in actor.roles
        or source.owner_id != actor.owner_id
        or source.namespace != "production"
    ):
        raise not_found()
    if not idempotency_key or len(idempotency_key) > 128:
        raise AppError(422, "idempotency_required", "需要有效副本操作标识")
    token = digest(dump([actor.owner_id, idempotency_key]))[:32]
    copy_id = "doc_copy_" + token
    version_id = "ver_copy_" + token
    build_id = "build_copy_" + token
    lineage = {
        "doc_id": source.doc_id,
        "version_id": source.document_version_id,
        "authorization_revision": source.authorization_revision,
        "owner_id": source.owner_id,
    }
    path = None
    created = False
    try:
        async with transaction() as conn:
            await fetch_one(
                "SELECT id FROM users WHERE id=%s FOR UPDATE",
                (actor.owner_id,),
                conn=conn,
            )
            await reauthorize_scope(
                ResolvedScope(
                    owner_id=actor.owner_id, namespace="production", documents=[source]
                ),
                conn=conn,
            )
            original = await owned_document(actor.owner_id, source.doc_id, conn=conn)
            existing = await fetch_one(
                "SELECT * FROM kb_documents WHERE doc_id=%s AND user_id=%s",
                (copy_id, actor.owner_id),
                conn=conn,
            )
            if existing:
                if load(existing["lineage_json"]) != lineage or existing["deleted_at"]:
                    raise conflict(
                        "copy_request_changed", "此副本操作已用于不同来源或来源已撤销"
                    )
                task = await fetch_one(
                    "SELECT task_id FROM quiz_tasks WHERE user_id=%s AND kind='ingest' AND idempotency_key=%s",
                    (actor.owner_id, f"ingest:{build_id}"),
                    conn=conn,
                )
            else:
                count = await fetch_one(
                    "SELECT COUNT(*) AS n FROM kb_documents WHERE user_id=%s AND purpose='evaluation' AND deleted_at IS NULL",
                    (actor.owner_id,),
                    conn=conn,
                )
                if count["n"] >= 300:
                    raise conflict("document_limit", "评测资料数量已达到上限")
                version = await fetch_one(
                    "SELECT * FROM kb_document_versions WHERE version_id=%s AND doc_id=%s AND owner_id=%s",
                    (source.document_version_id, source.doc_id, actor.owner_id),
                    conn=conn,
                )
                raw = artifacts().resolve_key(version["storage_key"]).read_bytes()
                if digest(raw) != source.source_sha256:
                    raise conflict("source_hash_mismatch", "原始资料校验和不匹配")
                key = f"raw/{version_id}.{version['file_type']}"
                path = artifacts().resolve_key(key)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
                created = True
                namespace = f"evaluation:{actor.owner_id}"
                await execute(
                    "INSERT INTO kb_documents(doc_id,user_id,file_name,file_type,file_size,purpose,namespace,lineage_json) VALUES(%s,%s,%s,%s,%s,'evaluation',%s,%s)",
                    (
                        copy_id,
                        actor.owner_id,
                        original["file_name"],
                        version["file_type"],
                        len(raw),
                        namespace,
                        dump(lineage),
                    ),
                    conn=conn,
                )
                await execute(
                    "INSERT INTO kb_document_versions(version_id,doc_id,owner_id,source_sha256,storage_key,file_type,file_bytes) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (
                        version_id,
                        copy_id,
                        actor.owner_id,
                        source.source_sha256,
                        key,
                        version["file_type"],
                        len(raw),
                    ),
                    conn=conn,
                )
                await execute(
                    "INSERT INTO kb_index_builds(build_id,doc_id,owner_id,version_id,namespace,index_profile_id,expected_document_revision) VALUES(%s,%s,%s,%s,%s,'legacy-char-v1',1)",
                    (build_id, copy_id, actor.owner_id, version_id, namespace),
                    conn=conn,
                )
                task = await job_service.enqueue_job(
                    actor.owner_id,
                    "ingest",
                    {
                        "doc_id": copy_id,
                        "version_id": version_id,
                        "build_id": build_id,
                        "document_revision": 1,
                        "purpose": "evaluation",
                    },
                    f"ingest:{build_id}",
                    mode="evaluation",
                    conn=conn,
                )
        created = False
        return await document_view(
            await owned_document(actor.owner_id, copy_id, purpose="evaluation"),
            task["task_id"] if task else None,
        )
    except BaseException:
        if created and path:
            await _discard_uncommitted_raw(actor.owner_id, version_id, path)
        raise


async def read_source(
    owner,
    doc_id,
    version_id,
    parse_artifact_id,
    block_id=None,
    *,
    start_char=None,
    end_char=None,
    purpose="production",
):
    row = await owned_document(owner, doc_id, purpose=purpose)
    build = await fetch_one(
        "SELECT * FROM kb_index_builds WHERE doc_id=%s AND owner_id=%s AND version_id=%s AND parse_artifact_id=%s AND status='ready' ORDER BY created_at DESC LIMIT 1",
        (doc_id, owner, version_id, parse_artifact_id),
    )
    if not build:
        raise not_found()
    result = BuildResult.model_validate(load(build["manifest_json"]))
    await reauthorize_scope(
        ResolvedScope(
            owner_id=owner,
            namespace=row["namespace"],
            documents=[result.to_source_manifest(row["authorization_revision"])],
        )
    )
    canonical = artifacts().load_canonical(result.canonical_artifact_key)
    block = (
        next((b for b in canonical.blocks if b.block_id == block_id), None)
        if block_id
        else canonical.blocks[0]
    )
    if not block:
        raise not_found()
    start = block.start_char if start_char is None else start_char
    end = block.end_char if end_char is None else end_char
    if not block.start_char <= start < end <= block.end_char:
        raise AppError(422, "invalid_source_range", "原文范围无效")
    excerpt = canonical.text[start:end]
    return {
        "doc_id": doc_id,
        "version_id": version_id,
        "parse_artifact_id": parse_artifact_id,
        "canonical_text_hash": canonical.canonical_text_hash,
        "source_sha256": canonical.source_sha256,
        "block_id": block.block_id,
        "excerpt": excerpt,
        "locator": {
            **block.model_dump(mode="json"),
            "start_char": start,
            "end_char": end,
            "quote_hash": digest(excerpt),
        },
        "blocks": [b.model_dump(mode="json") for b in canonical.blocks],
        "sections": [s.model_dump(mode="json") for s in canonical.sections],
    }


async def read_evidence(owner, quiz_id, evidence_id):
    from app.services.learning_service import owned_quiz

    quiz = await owned_quiz(owner, quiz_id)
    scope = load(quiz["source_scope_json"])
    if scope:
        await reauthorize_scope(scope)
    run = await fetch_one(
        "SELECT evidence_artifact_key FROM rag_runs WHERE run_id=%s AND owner_id=%s",
        (quiz["rag_run_id"], owner),
    )
    if not run or not run["evidence_artifact_key"]:
        raise not_found()
    payload = json.loads(
        artifacts().resolve_key(run["evidence_artifact_key"]).read_bytes()
    )
    pack = payload.get("evidence_pack", payload)
    evidence = next(
        (e for e in pack.get("evidence", []) if e["evidence_id"] == evidence_id), None
    )
    if not evidence or evidence["owner_id"] != owner:
        raise not_found()
    return evidence


async def cleanup_document(owner, doc_id, store):
    """Called serially by the sole index owner, after in-flight local writes finish.

    Tombstones make every read fail immediately. This separate idempotent sweep
    removes both published and losing attempts and canonical/raw payloads.
    """
    from app.rag.contracts import stable_hash

    row = await fetch_one(
        "SELECT * FROM kb_documents WHERE doc_id=%s AND user_id=%s", (doc_id, owner)
    )
    if not row or row["deleted_at"] is None:
        raise conflict("source_not_revoked", "只能清理已撤销的资料")
    from app.services.qa_service import purge_document
    from app.services.learning_cleanup_service import purge_document as purge_learning

    await purge_document(owner, doc_id)
    await purge_learning(owner, doc_id)
    remaining = store.purge_document(
        owner_id=owner, namespace=row["namespace"], doc_id=doc_id
    )
    if remaining:
        raise conflict("cleanup_pending", "资料清理仍有残留")
    versions = await fetch_all(
        "SELECT version_id,storage_key FROM kb_document_versions WHERE doc_id=%s AND owner_id=%s",
        (doc_id, owner),
    )
    for version in versions:
        store.resolve_key(version["storage_key"]).unlink(missing_ok=True)
        canonical_dir = store.resolve_key(
            "sources/"
            + stable_hash([owner, row["namespace"], doc_id, version["version_id"]])[:32]
        )
        if canonical_dir.exists():
            for artifact in canonical_dir.glob("*.json"):
                if not artifact.resolve().is_relative_to(store.root):
                    raise ValueError("Canonical cleanup path escaped storage root")
                artifact.unlink()
    runs = await fetch_all("SELECT * FROM rag_runs WHERE owner_id=%s", (owner,))
    for run in runs:
        manifest = load(run["manifest_json"], {})
        scope = manifest.get("scope", manifest.get("resolved_scope", {})) or {}
        if any(d.get("doc_id") == doc_id for d in scope.get("documents", [])):
            if run["evidence_artifact_key"]:
                file = store.resolve_key(run["evidence_artifact_key"])
                if file.exists():
                    payload = load(file.read_text(encoding="utf-8"), {})
                    for evidence in payload.get("evidence_pack", payload).get(
                        "evidence", []
                    ):
                        if evidence.get("snapshot_artifact_key"):
                            store.resolve_key(evidence["snapshot_artifact_key"]).unlink(
                                missing_ok=True
                            )
            for key in (run["evidence_artifact_key"], run["debug_artifact_key"]):
                if key:
                    store.resolve_key(key).unlink(missing_ok=True)
            await execute(
                "UPDATE rag_runs SET evidence_artifact_key=NULL,debug_artifact_key=NULL,status='source_revoked' WHERE run_id=%s",
                (run["run_id"],),
            )
    assets = await fetch_all(
        "SELECT asset_id,storage_key,source_scope_json FROM user_assets WHERE owner_id=%s AND source_scope_json IS NOT NULL",
        (owner,),
    )
    for asset in assets:
        if any(
            d.get("doc_id") == doc_id
            for d in load(asset["source_scope_json"], {}).get("documents", [])
        ):
            store.resolve_key(asset["storage_key"]).unlink(missing_ok=True)
            await execute(
                "DELETE FROM user_assets WHERE asset_id=%s AND owner_id=%s",
                (asset["asset_id"], owner),
            )
    async with transaction() as conn:
        await execute(
            "DELETE FROM kb_nodes WHERE doc_id=%s AND owner_id=%s AND parent_id IS NOT NULL",
            (doc_id, owner),
            conn=conn,
        )
        await execute(
            "DELETE FROM kb_nodes WHERE doc_id=%s AND owner_id=%s",
            (doc_id, owner),
            conn=conn,
        )
        await execute(
            "UPDATE kb_index_builds SET status='deleted',manifest_json=NULL,canonical_artifact_key=NULL WHERE doc_id=%s AND owner_id=%s",
            (doc_id, owner),
            conn=conn,
        )
        await execute(
            "UPDATE kb_documents SET active_build_id=NULL,active_version_id=NULL WHERE doc_id=%s AND user_id=%s",
            (doc_id, owner),
            conn=conn,
        )
        datasets = await fetch_all(
            "SELECT dataset_id,version,samples_json,artifact_key FROM eval_datasets WHERE owner_id=%s AND status='revoked'",
            (owner,),
            conn=conn,
        )
        for dataset in datasets:
            if any(
                ref.get("doc_id") == doc_id
                for sample in load(dataset["samples_json"], [])
                for ref in sample.get("source_refs", [])
            ):
                if dataset["artifact_key"]:
                    store.resolve_key(dataset["artifact_key"]).unlink(missing_ok=True)
                affected = await fetch_all(
                    "SELECT run_id FROM eval_runs WHERE dataset_id=%s AND dataset_version=%s",
                    (dataset["dataset_id"], dataset["version"]),
                    conn=conn,
                )
                for run in affected:
                    results = await fetch_all(
                        "SELECT artifact_key FROM eval_results WHERE run_id=%s",
                        (run["run_id"],),
                        conn=conn,
                    )
                    for result in results:
                        if result["artifact_key"]:
                            store.resolve_key(result["artifact_key"]).unlink(
                                missing_ok=True
                            )
                    await execute(
                        "UPDATE eval_results SET artifact_json=NULL,artifact_key=NULL,sample_json=JSON_OBJECT(),review_json=NULL,error_code='source_revoked' WHERE run_id=%s",
                        (run["run_id"],),
                        conn=conn,
                    )
                    await execute(
                        "UPDATE eval_runs SET status='cancelled',stop_reason='source_revoked' WHERE run_id=%s",
                        (run["run_id"],),
                        conn=conn,
                    )
                await execute(
                    "UPDATE eval_datasets SET samples_json=JSON_ARRAY(),artifact_key=NULL WHERE dataset_id=%s AND version=%s",
                    (dataset["dataset_id"], dataset["version"]),
                    conn=conn,
                )
