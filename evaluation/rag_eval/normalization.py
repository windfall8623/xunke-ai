"""Explicit JSON adaptation for the production v1 artifact contract."""

from __future__ import annotations

import copy

from .contracts import canonical_hash


def normalize_artifact(artifact: dict) -> dict:
    result = copy.deepcopy(artifact)
    result["_source_artifact_hash"] = canonical_hash(artifact)
    if result.get("case_type") in {"practice_generation", "answer_grading"}:
        # Private payloads and their decimal strings are hash-bound. Derive only
        # outer helper views; the outer ledger is the sole accounting source.
        usage = result.setdefault("usage", {})
        usage.setdefault("stages_ms", usage.get("stage_ms", {}))
        if result["case_type"] == "practice_generation":
            practice = result.get("practice") or {}
            pack = practice.get("evidence_pack", {})
            result["evidence"] = copy.deepcopy(pack.get("evidence", []))
            result["context_evidence_ids"] = copy.deepcopy(
                pack.get("provided_evidence_ids", [])
            )
            usage.setdefault("context_tokens", pack.get("context_tokens"))
        return result
    if result.get("case_type") == "qa":
        result.setdefault("status", "completed")
        trace = result.get("trace", [])
        retrieval = next(
            (item for item in trace if item.get("stage") == "retrieve"), {}
        )
        result.setdefault(
            "context_evidence_ids",
            [item["evidence_id"] for item in result.get("evidence", [])],
        )
        usage = result.setdefault("usage", {})
        usage.setdefault("context_tokens", retrieval.get("context_tokens"))
        usage.setdefault("stages_ms", usage.get("stage_ms", {}))
        return result
    if result.get("schema_version") == "retrieval-artifact.v1":
        result["schema_version"] = "1"
        result["input_schema_version"] = "retrieval-artifact.v1"
        result.setdefault("status", "completed")
        trace = result.get("trace", {})
        result.setdefault(
            "candidates", trace.get("candidates", result.get("evidence", []))
        )
        result.setdefault("context_evidence_ids", trace.get("provided_evidence_ids"))
        usage = result.setdefault("usage", {})
        usage.setdefault("context_tokens", trace.get("context_tokens"))
        usage.setdefault("stages_ms", usage.get("stage_ms", {}))
        return result
    if result.get("schema_version") != "quiz-artifact.v1":
        return result
    result["schema_version"] = "1"
    result["input_schema_version"] = "quiz-artifact.v1"
    if "status" not in result:
        result["status"] = (
            "completed"
            if result.get("validation", {}).get("passed", True)
            else "failed"
        )
    pack = result.get("evidence_pack", {})
    result.setdefault("evidence", pack.get("evidence", []))
    result.setdefault("context_evidence_ids", pack.get("provided_evidence_ids", []))
    usage = result.setdefault("usage", {})
    usage.setdefault("context_tokens", pack.get("context_tokens"))
    usage.setdefault("stages_ms", usage.get("stage_ms", {}))
    for question in result.get("questions", []):
        question["_source_question_hash"] = canonical_hash(question)
        question["question_id"] = question.pop("id", question.get("question_id"))
        kind = question.get("type")
        question["options"] = [
            {"id": item.get("key", item.get("id")), "text": item.get("text")}
            for item in question.get("options", [])
        ]
        if kind in {"single", "multiple"}:
            question["type"] = (
                "single_choice" if kind == "single" else "multiple_choice"
            )
        elif kind == "judge":
            question["type"] = "true_false"
            answer = question.get("answer", [])
            selected = next(
                (
                    item["text"]
                    for item in question["options"]
                    if len(answer) == 1 and item["id"] == answer[0]
                ),
                None,
            )
            truth = {
                "正确": True,
                "错误": False,
                "对": True,
                "错": False,
                "true": True,
                "false": False,
                "是": True,
                "否": False,
            }
            if isinstance(selected, str) and selected.strip().casefold() in truth:
                question["answer"] = truth[selected.strip().casefold()]
                question["options"] = []
    return result
