"""Synthetic HTTP -> QA prediction -> scoring -> export with real SQL and sources."""

import copy
import json
import uuid

import httpx
import pytest

from tests.platform.qa_helpers import qa_context as qa_context
from tests.platform.test_evaluation import policy_dataset
from tests.platform.test_qa_integration import (
    SourceEchoTransport,
    connect_metered_generator,
)


async def qa_dataset(ctx, *, expected_error=None):
    from app.core.db import execute, fetch_one
    from app.core.values import digest, load
    from app.rag.contracts import BuildResult

    owner = ctx["actor"].owner_id
    await execute("UPDATE users SET role='admin' WHERE id=%s", (owner,))
    uploaded = await ctx["api"].post(
        "/api/v1/eval/documents",
        files={"file": ("qa-synthetic.txt", "光合作用需要光。".encode(), "text/plain")},
    )
    assert uploaded.status_code == 202, uploaded.text
    document = uploaded.json()["data"]
    await ctx["worker"].run_once(task_id=document["task_id"])
    row = await fetch_one(
        "SELECT b.manifest_json FROM kb_index_builds b JOIN kb_documents d ON d.active_build_id=b.build_id "
        "WHERE d.doc_id=%s AND d.user_id=%s",
        (document["doc_id"], owner),
    )
    assert row, document
    build = BuildResult.model_validate(load(row["manifest_json"]))
    canonical = ctx["store"].load_canonical(build.canonical_artifact_key)
    reference = {
        "doc_id": build.doc_id,
        "source_version_id": build.document_version_id,
        "parse_artifact_id": build.parse_artifact_id,
        "source_sha256": canonical.source_sha256,
        "canonical_text_hash": canonical.canonical_text_hash,
        "family_id": "qa-test-" + document["doc_id"],
        "license": "synthetic-test-fixture",
        "owner_id": owner,
        "namespace": f"evaluation:{owner}",
    }
    block = canonical.blocks[0]
    span = {
        **{
            key: reference[key]
            for key in (
                "doc_id",
                "source_version_id",
                "parse_artifact_id",
                "canonical_text_hash",
            )
        },
        "block_id": block.block_id,
        "start_char": block.start_char,
        "end_char": block.end_char,
        "quote_hash": digest(canonical.text[block.start_char : block.end_char]),
    }
    sample = {
        "schema_version": "1",
        "sample_id": "qa-synthetic",
        "case_type": "qa",
        "family_ids": [reference["family_id"]],
        "split": "dev",
        "source_refs": [reference],
        "question": "它需要什么？" if not expected_error else "光合作用需要什么？",
        "history": []
        if expected_error
        else [{"question": "这个过程是什么？", "answer": "光合作用。"}],
        "annotation": {"provenance": "model_draft", "review_records": []},
    }
    if expected_error:
        # Omitted nullable status must have the same meaning at import and run.
        sample["expected_error_code"] = expected_error
    else:
        sample.update(
            expected_answer_status="answered",
            gold_evidence_groups=[
                {"group_id": "light", "alternatives": [{"spans": [span]}]}
            ],
        )
    payload = policy_dataset()
    payload["name"] = "Synthetic QA integration fixture"
    payload["manifest"]["sources"] = [reference]
    payload["samples"] = [sample]
    return payload, document


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_failure", [False, True])
async def test_qa_evaluation_predicts_scores_and_exports_without_learning_writes(
    qa_context, platform_settings, provider_failure
):
    from rag_eval.metrics import score_sample

    from app.core.db import fetch_all, fetch_one
    from app.main import app

    ctx = qa_context

    async def fail_answer(request):
        if provider_failure and request["task"] == "qa_answer":
            raise RuntimeError("synthetic provider failure; no network I/O")

    transport = SourceEchoTransport(before_reply=fail_answer)
    connect_metered_generator(ctx, platform_settings, transport)
    payload, document = await qa_dataset(
        ctx, expected_error="GENERATION_VALIDATION_FAILED" if provider_failure else None
    )
    if not provider_failure:
        for malformed_status in ([], {}):
            invalid = copy.deepcopy(payload)
            invalid["samples"][0]["expected_answer_status"] = malformed_status
            rejected = await ctx["api"].post("/api/v1/eval/datasets", json=invalid)
            assert rejected.status_code == 409, rejected.text
            assert rejected.json()["error_code"] == "dataset_validation_failed"

    created = await ctx["api"].post("/api/v1/eval/datasets", json=payload)
    assert created.status_code == 201, created.text
    dataset_id = created.json()["data"]["dataset_id"]
    path = f"/api/v1/eval/datasets/{dataset_id}/versions/1"
    # This simulates the review API in the isolated test DB, not a human review
    # of the separately delivered 60-case model_draft engineering corpus.
    reviewed = await ctx["api"].post(
        path + "/samples/qa-synthetic/review",
        json={
            "expected_revision": 1,
            "verdict": "approved",
            "comment": "Synthetic API transition test",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    frozen = await ctx["api"].post(path + "/freeze", json={"expected_revision": 2})
    assert frozen.status_code == 200, frozen.text
    body = {
        "dataset_id": dataset_id,
        "dataset_version": 1,
        "pipeline_id": "bm25-v1",
        "repeat_count": 1,
        "max_cost_cny": 2,
    }
    estimate = await ctx["api"].get(
        "/api/v1/eval/runs/estimate",
        params={key: value for key, value in body.items() if key != "max_cost_cny"},
    )
    assert estimate.status_code == 200, estimate.text
    generation = next(
        part
        for part in estimate.json()["data"]["components"]
        if part["stage"] == "generation"
    )
    assert generation["first_attempt_calls"] == (2 if provider_failure else 3)
    assert generation["retry_scenario_calls"] <= 5
    created = await ctx["api"].post(
        "/api/v1/eval/runs", json=body, headers={"Idempotency-Key": uuid.uuid4().hex}
    )
    assert created.status_code == 202, created.text
    run = created.json()["data"]
    assert run["manifest"]["judge_calibrated"] is False
    job = await fetch_one(
        "SELECT task_id,scope_json FROM quiz_tasks WHERE kind='eval_sample' AND user_id=%s "
        "AND JSON_UNQUOTE(JSON_EXTRACT(request_json,'$.run_id'))=%s",
        (ctx["actor"].owner_id, run["run_id"]),
    )
    assert await ctx["worker"].run_once(task_id=job["task_id"])
    result = (
        await ctx["api"].get(f"/api/v1/eval/runs/{run['run_id']}/results")
    ).json()["data"]["items"][0]
    assert result["case_type"] == "qa" and result["status"] == "pending_scoring", result
    artifact = result["artifact"]
    if provider_failure:
        assert artifact["status"] == "failed"
        assert artifact["error_code"] == "GENERATION_VALIDATION_FAILED"
        assert artifact["evidence"] == []
        assert all(
            key not in artifact
            for key in ("answer_status", "blocks", "retrieval_query")
        )
    else:
        assert artifact["answer_status"] == "answered"
        assert artifact["usage"]["llm_calls"] == 3
        assert {item["doc_id"] for item in artifact["evidence"]} == {document["doc_id"]}
        assert all(
            item["namespace"] == f"evaluation:{ctx['actor'].owner_id}"
            for item in artifact["evidence"]
        )
        assert transport.calls[0]["history"] == payload["samples"][0]["history"]
    assert "questions" not in artifact and "observations" not in artifact

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Authorization": f"Bearer {platform_settings.eval_worker_token}"},
    ) as scorer:
        claimed = await scorer.post(
            "/api/v1/internal/eval/scoring/claim",
            json={"worker_id": "synthetic-qa-scorer", "run_id": run["run_id"]},
        )
        assert claimed.status_code == 200, claimed.text
        leased = claimed.json()["data"]
        assert (
            leased["sample"]["source_refs"][0]["canonical_text"] == "光合作用需要光。"
        )
        metrics = score_sample(leased["sample"], leased["artifact"], leased["config"])
        if provider_failure:
            assert metrics["qa_failure_behavior_match"]["value"] == 1
        else:
            for key in (
                "qa_answer_status_match",
                "qa_answer_structure_validity",
                "qa_citation_validity",
                "qa_fact_citation_coverage",
                "qa_evidence_group_recall",
                "qa_all_evidence_hit",
            ):
                assert metrics[key]["value"] == 1, (key, metrics[key])
        for key in ("qa_correctness", "qa_faithfulness"):
            assert (
                metrics[key]["status"] == "na"
                and metrics[key]["reason"] == "not_evaluated"
            )
        scored = await scorer.post(
            f"/api/v1/internal/eval/scoring/{leased['result_id']}/complete",
            json={
                "lease_token": leased["lease_token"],
                "attempt": leased["attempt"],
                "metrics": metrics,
            },
        )
        assert scored.status_code == 200, scored.text

    finished = (await ctx["api"].get(f"/api/v1/eval/runs/{run['run_id']}")).json()[
        "data"
    ]
    assert finished["status"] == "completed", finished
    assert finished["comparison_eligible"] is False
    assert finished["manifest"]["human_adjudication_complete"] is False
    exported = await ctx["api"].get(
        f"/api/v1/eval/runs/{run['run_id']}/export?format=jsonl"
    )
    assert exported.status_code == 200, exported.text
    row = json.loads(exported.text.strip())
    assert (
        row["case_type"] == "qa" and row["metrics"]["qa_correctness"]["value"] is None
    )
    for table, owner_column in (
        ("qa_sessions", "owner_id"),
        ("qa_answers", "owner_id"),
        ("quiz_sessions", "user_id"),
        ("reports", "user_id"),
    ):
        assert (
            await fetch_one(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {owner_column}=%s",
                (ctx["actor"].owner_id,),
            )
        )["n"] == 0
    assert (
        await fetch_one(
            "SELECT total_xp FROM users WHERE id=%s", (ctx["actor"].owner_id,)
        )
    )["total_xp"] == 0
    calls = await fetch_all(
        "SELECT mode FROM provider_calls WHERE operation_id=%s", (job["task_id"],)
    )
    assert len(calls) == (1 if provider_failure else 3)
    assert all(call["mode"] == "evaluation" for call in calls)
