"""Owner-authorized feedback -> reviewed, deidentified evaluation drafts.

The generated answer and the complaint are never promoted as gold. Copies retain
source lineage; final datasets are newly versioned and still need annotation.
"""

import copy

from app.core.db import execute, fetch_all, fetch_one, transaction
from app.core.errors import AppError, conflict, not_found
from app.core.values import digest, dump, iso, load, now
from app.rag.contracts import BuildResult, ResolvedScope
from app.services import eval_dataset_service as datasets
from app.services import source_service as sources
from app.services.learning_service import owned_quiz


async def owned_feedback(owner, feedback_id, *, conn=None, lock=False):
    row = await fetch_one(
        "SELECT * FROM quiz_feedback WHERE feedback_id=%s AND owner_id=%s"
        + (" FOR UPDATE" if lock else ""),
        (feedback_id, owner),
        conn=conn,
    )
    if not row:
        raise not_found()
    return row


def view(row):
    review = load(row["review_json"], {})
    return {
        **{
            key: row[key]
            for key in ("feedback_id", "quiz_id", "question_id", "reason", "status")
        },
        "comment": row["comment"] or "",
        "allow_evaluation_use": bool(row["allow_evaluation"]),
        "revision": review.get("revision", 0),
        "created_at": iso(row["created_at"]),
        "review": review.get("latest_review"),
        "promotion": review.get("promotion"),
        "access_scope": "owner_only",
    }


async def create_feedback(actor, quiz_id, body):
    quiz = await owned_quiz(actor.owner_id, quiz_id)
    if body.question_id not in {q["id"] for q in load(quiz["questions_json"], [])}:
        raise not_found()
    feedback_id = (
        "feedback_" + digest(dump([actor.owner_id, quiz_id, body.model_dump()]))[:32]
    )
    await execute(
        "INSERT INTO quiz_feedback(feedback_id,owner_id,quiz_id,question_id,rag_run_id,reason,comment,allow_evaluation) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE feedback_id=feedback_id",
        (
            feedback_id,
            actor.owner_id,
            quiz_id,
            body.question_id,
            quiz["rag_run_id"],
            body.reason,
            body.comment,
            body.allow_evaluation_use,
        ),
    )
    return view(await owned_feedback(actor.owner_id, feedback_id))


async def list_feedback(owner, *, page=1, page_size=50):
    rows = await fetch_all(
        "SELECT * FROM quiz_feedback WHERE owner_id=%s ORDER BY created_at DESC,feedback_id LIMIT %s OFFSET %s",
        (owner, page_size, (page - 1) * page_size),
    )
    total = await fetch_one(
        "SELECT COUNT(*) AS n FROM quiz_feedback WHERE owner_id=%s", (owner,)
    )
    return {"items": [view(row) for row in rows], "total": total["n"]}


async def review_feedback(actor, feedback_id, body):
    async with transaction() as conn:
        row = await owned_feedback(actor.owner_id, feedback_id, conn=conn, lock=True)
        record = load(row["review_json"], {})
        if record.get("revision", 0) != body.expected_revision:
            raise conflict()
        if row["status"] == "promoted":
            raise conflict(
                "feedback_already_promoted", "该反馈已进入候选数据集，请在新版本中修订"
            )
        latest = {
            "verdict": body.verdict,
            "comment": body.comment,
            "reviewer_id": actor.owner_id,
            "reviewed_at": iso(now()),
            "provenance": "human",
        }
        record.update(
            revision=body.expected_revision + 1,
            latest_review=latest,
            review_records=[*record.get("review_records", []), latest],
        )
        if body.verdict != "approved":
            record.pop("promotion", None)
        await execute(
            "UPDATE quiz_feedback SET status=%s,review_json=%s WHERE feedback_id=%s",
            (body.verdict, dump(record), feedback_id),
            conn=conn,
        )
    return view(await owned_feedback(actor.owner_id, feedback_id))


async def _quiz_source_context(actor, row, *, conn=None):
    quiz = await owned_quiz(actor.owner_id, row["quiz_id"], conn=conn)
    scope = ResolvedScope.model_validate(
        load(quiz["source_scope_json"])
        or {"owner_id": actor.owner_id, "namespace": "production", "documents": []}
    )
    await sources.reauthorize_scope(scope, conn=conn)
    return quiz, scope


def _promotion_response(row, documents):
    feedback = view(row)
    promotion = feedback["promotion"]
    return {
        "status": promotion["state"],
        "feedback": feedback,
        "documents": documents,
        "dataset_id": promotion.get("dataset_id"),
        "dataset_version": promotion.get("dataset_version"),
    }


async def promote_feedback(actor, feedback_id, body):
    row = await owned_feedback(actor.owner_id, feedback_id)
    if not row["allow_evaluation"]:
        raise conflict("evaluation_consent_required", "反馈提交时未授权资料用于评测")
    if row["status"] not in ("approved", "preparing", "promoted"):
        raise conflict("feedback_review_required", "请先人工审核该反馈")
    request = body.model_dump(exclude={"expected_revision"}, exclude_none=True)
    if not request["redacted_request"].strip() or not request["name"].strip():
        raise AppError(
            422, "redacted_request_required", "请填写脱敏后的学习请求和数据集名称"
        )
    request_hash = digest(dump(request))
    record = load(row["review_json"], {})
    prior = record.get("promotion")
    if prior and prior["request_hash"] != request_hash:
        raise conflict(
            "promotion_conflict", "资料准备后请求已固定，请先将反馈退回修改再重新审核"
        )
    quiz, scope = await _quiz_source_context(actor, row)
    if prior and prior["state"] == "promoted":
        await datasets.get_dataset(
            actor.owner_id, prior["dataset_id"], prior["dataset_version"]
        )
        return _promotion_response(row, prior.get("documents", []))
    if record.get("revision", 0) != body.expected_revision:
        raise conflict()
    # Reserve the promotion identity before copying. Copy operations themselves
    # use stable owner+feedback+source keys, and never inherit a feedback row lock.
    async with transaction() as conn:
        current = await owned_feedback(
            actor.owner_id, feedback_id, conn=conn, lock=True
        )
        current_record = load(current["review_json"], {})
        existing = current_record.get("promotion")
        if current_record.get("revision", 0) != body.expected_revision or current[
            "status"
        ] not in ("approved", "preparing"):
            if (
                existing
                and existing.get("state") == "promoted"
                and existing.get("request_hash") == request_hash
            ):
                return _promotion_response(current, existing.get("documents", []))
            raise conflict()
        if existing and existing["request_hash"] != request_hash:
            raise conflict("promotion_conflict", "同一反馈资料准备参数不能改变")
        current_record["promotion"] = {
            "state": "preparing",
            "request_hash": request_hash,
            "request": request,
            "documents": existing.get("documents", []) if existing else [],
        }
        await execute(
            "UPDATE quiz_feedback SET status='preparing',review_json=%s WHERE feedback_id=%s",
            (dump(current_record), feedback_id),
            conn=conn,
        )
    copies = []
    for source in scope.documents:
        copies.append(
            await sources.copy_for_evaluation(
                actor, source, f"feedback:{feedback_id}:{source.doc_id}"
            )
        )
    async with transaction() as conn:
        current = await owned_feedback(
            actor.owner_id, feedback_id, conn=conn, lock=True
        )
        current_record = load(current["review_json"], {})
        completed = current_record.get("promotion", {})
        if (
            completed.get("state") == "promoted"
            and completed.get("request_hash") == request_hash
        ):
            return _promotion_response(current, completed.get("documents", []))
        if (
            current_record.get("revision", 0) != body.expected_revision
            or current_record.get("promotion", {}).get("request_hash") != request_hash
        ):
            raise conflict()
        current_record["promotion"]["documents"] = copies
        await execute(
            "UPDATE quiz_feedback SET review_json=%s WHERE feedback_id=%s",
            (dump(current_record), feedback_id),
            conn=conn,
        )
    if any(doc["status"] != "ready" for doc in copies):
        return _promotion_response(
            await owned_feedback(actor.owner_id, feedback_id), copies
        )
    refs = []
    mapped = {}
    for index, (source, doc) in enumerate(zip(scope.documents, copies, strict=True)):
        build_row = await fetch_one(
            "SELECT manifest_json FROM kb_index_builds WHERE build_id=%s AND owner_id=%s AND status='ready'",
            (doc["active_build_id"], actor.owner_id),
        )
        if not build_row:
            raise not_found()
        build = BuildResult.model_validate(load(build_row["manifest_json"]))
        canonical = sources.artifacts().load_canonical(build.canonical_artifact_key)
        if (
            canonical.canonical_text_hash != source.canonical_text_hash
            or canonical.source_sha256 != source.source_sha256
        ):
            raise conflict(
                "feedback_copy_mapping_failed", "原文解析发生变化，需要人工映射后再导入"
            )
        original = sources.artifacts().load_canonical(source.canonical_artifact_key)
        selected = [
            section
            for section in original.sections
            if section.section_id in source.section_ids
        ]
        mapped_sections = [
            next(
                (
                    section.section_id
                    for section in canonical.sections
                    if (section.start_char, section.end_char, section.title)
                    == (old.start_char, old.end_char, old.title)
                ),
                None,
            )
            for old in selected
        ]
        if any(value is None for value in mapped_sections):
            raise conflict(
                "feedback_copy_mapping_failed", "章节映射发生变化，需要人工确认"
            )
        ref = {
            "doc_id": doc["doc_id"],
            "source_version_id": canonical.document_version_id,
            "parse_artifact_id": canonical.parse_artifact_id,
            "canonical_text_hash": canonical.canonical_text_hash,
            "source_sha256": canonical.source_sha256,
            "family_id": "source-family-"
            + digest(dump([actor.owner_id, source.doc_id]))[:24],
            "owner_id": actor.owner_id,
            "namespace": f"evaluation:{actor.owner_id}",
            "section_ids": mapped_sections,
            "license": "private_owner_authorized_for_evaluation",
            "authorization_status": "authorized",
            "title": f"反馈授权资料 {index + 1}",
        }
        refs.append(ref)
        mapped[source.doc_id] = (canonical, ref)
    candidate_spans = []
    question = next(
        q for q in load(quiz["questions_json"]) if q["id"] == row["question_id"]
    )
    for evidence_id in question.get("citation_refs", []):
        evidence = await sources.read_evidence(
            actor.owner_id, quiz["quiz_id"], evidence_id
        )
        if (
            evidence.get("source_type") != "document"
            or evidence.get("doc_id") not in mapped
        ):
            continue
        canonical, ref = mapped[evidence["doc_id"]]
        locator = evidence["locator"]
        start, end = locator["start_char"], locator["end_char"]
        if digest(canonical.text[start:end]) != locator["quote_hash"]:
            raise conflict("feedback_copy_mapping_failed", "引用原文校验未通过")
        for block in canonical.blocks:
            left, right = max(start, block.start_char), min(end, block.end_char)
            if left < right:
                candidate_spans.append(
                    {
                        **{
                            key: ref[key]
                            for key in (
                                "doc_id",
                                "source_version_id",
                                "parse_artifact_id",
                                "canonical_text_hash",
                            )
                        },
                        "block_id": block.block_id,
                        "start_char": left,
                        "end_char": right,
                        "quote_hash": digest(canonical.text[left:right]),
                    }
                )
    sample = {
        "schema_version": "1",
        "sample_id": "feedback-" + digest(feedback_id)[:24],
        "case_type": "quiz",
        "user_input": body.redacted_request,
        "question_count": body.question_count,
        "source_policy": "strict_docs" if refs else "topic",
        "source_refs": refs,
        "family_ids": sorted({ref["family_id"] for ref in refs})
        or ["feedback-family-" + digest(feedback_id)[:24]],
        "split": "dev",
        "tags": ["feedback_regression", row["reason"]],
        "expected_outcome": "generate",
        "source_sufficient": False,
        "candidate_evidence": candidate_spans,
        "gold_evidence_groups": [],
        "question_rubrics": [],
        "annotation": {
            "provenance": "feedback_candidate",
            "human_review_status": "pending",
            "review_records": [],
        },
        "feedback_reference": {
            "feedback_id": feedback_id,
            "reason": row["reason"],
            "original_question_hash": digest(dump(question)),
        },
    }
    manifest = {
        "state": "draft",
        "annotation_version": "feedback-candidate-v1",
        "sources": refs,
        "review": {"checklist": {}},
        "purpose": "private regression candidates; human labels required",
    }
    samples = [sample]
    parent_version = None
    if body.dataset_id:
        parent = await fetch_one(
            "SELECT * FROM eval_datasets WHERE dataset_id=%s AND owner_id=%s ORDER BY version DESC LIMIT 1",
            (body.dataset_id, actor.owner_id),
        )
        if not parent or parent["status"] == "revoked":
            raise not_found()
        parent_version = parent["version"]
        manifest = copy.deepcopy(load(parent["manifest_json"]))
        manifest.update(
            state="draft", release_gold_status="draft", review={"checklist": {}}
        )
        for field in (
            "counts",
            "frozen_by",
            "frozen_at",
            "review_summary",
            "formal_gold_eligible",
            "source_similarity_audit",
            "sample_clusters",
        ):
            manifest.pop(field, None)
        manifest["sources"] = [*manifest.get("sources", []), *refs]
        samples = [*load(parent["samples_json"]), sample]
    async with transaction() as conn:
        await sources.reauthorize_scope(scope, conn=conn)
        await datasets.validated(actor.owner_id, manifest, samples, conn=conn)
        current = await owned_feedback(
            actor.owner_id, feedback_id, conn=conn, lock=True
        )
        current_record = load(current["review_json"], {})
        if current_record.get("promotion", {}).get("state") == "promoted":
            return _promotion_response(
                current, current_record["promotion"].get("documents", [])
            )
        if (
            current_record.get("revision", 0) != body.expected_revision
            or current_record.get("promotion", {}).get("request_hash") != request_hash
        ):
            raise conflict()
        created = await datasets.store_draft(
            actor,
            body.name,
            manifest,
            samples,
            dataset_id=body.dataset_id,
            expected_parent_version=parent_version,
            conn=conn,
        )
        current_record["promotion"].update(
            state="promoted",
            documents=copies,
            dataset_id=created["dataset_id"],
            dataset_version=created["version"],
        )
        current_record["revision"] = body.expected_revision + 1
        await execute(
            "UPDATE quiz_feedback SET status='promoted',review_json=%s WHERE feedback_id=%s",
            (dump(current_record), feedback_id),
            conn=conn,
        )
    return _promotion_response(
        await owned_feedback(actor.owner_id, feedback_id), copies
    )
