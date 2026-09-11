"""QA structure and evidence checks. No model, backend import or semantic claims."""

from __future__ import annotations

from collections import Counter

from .contracts import metric, not_applicable, uncertain
from .evidence import citation_check, context_of, coverage, source_identity

ANSWER_STATUSES = {
    "answered",
    "partial",
    "needs_clarification",
    "insufficient_evidence",
    "conflicting_sources",
}
SUBSTANTIVE_STATUSES = {"answered", "partial", "conflicting_sources"}
FAILURE_STATUSES = {"failed", "cancelled", "timeout"}
NOTICE_TEXTS = {
    "needs_clarification": "请补充或明确问题中指代的对象、条件或资料范围。",
    "insufficient_evidence": "在当前选定的资料中未找到足够依据，暂时无法回答。",
    "partial": "当前资料只能支持以下部分回答，其余内容缺少依据。",
    "conflicting_sources": "当前资料存在不一致的表述，以下分别列出各来源的依据。",
}


def _text(value, maximum):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _in(value, options):
    return isinstance(value, str) and value in options


def validate_qa_sample(sample: dict) -> list[str]:
    """Portable dataset rules, mirrored by the public Pydantic exchange schema."""
    errors = []
    if not _text(sample.get("question"), 2000):
        errors.append("qa_question_invalid")
    status, error = (
        sample.get("expected_answer_status"),
        sample.get("expected_error_code"),
    )
    if status is not None and not _in(status, ANSWER_STATUSES):
        errors.append("qa_expected_status_invalid")
    if status is None and not _text(error, 128):
        errors.append("qa_expected_error_required")
    if status is not None and error is not None:
        errors.append("qa_status_error_conflict")
    history = sample.get("history", [])
    valid_history = isinstance(history, list) and len(history) <= 6
    size = 0
    if valid_history:
        for turn in history:
            if (
                not isinstance(turn, dict)
                or set(turn) != {"question", "answer"}
                or not _text(turn.get("question"), 2000)
                or not _text(turn.get("answer"), 16000)
            ):
                valid_history = False
                break
            size += (
                len(turn["question"].encode("utf-8"))
                + len(turn["answer"].encode("utf-8"))
                + 64
            )
    if not valid_history or size > 8000:
        errors.append("qa_history_invalid")
    refs = sample.get("source_refs")
    if not isinstance(refs, list) or not 1 <= len(refs) <= 5:
        errors.append("qa_source_scope_missing")
    elif len({source_identity(ref)[0] for ref in refs}) != len(refs):
        errors.append("qa_source_scope_duplicate")
    if _in(status, SUBSTANTIVE_STATUSES) and not sample.get("gold_evidence_groups"):
        errors.append("qa_answer_gold_missing")
    return errors


def structure_errors(artifact: dict) -> list[str]:
    status, blocks = artifact.get("answer_status"), artifact.get("blocks")
    errors = []
    if not _in(status, ANSWER_STATUSES):
        errors.append("invalid_answer_status")
    if not _in(artifact.get("status", "completed"), {"completed"} | FAILURE_STATUSES):
        errors.append("invalid_execution_status")
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= 12:
        return [*errors, "invalid_answer_blocks"]
    ids, facts, notices, byte_count = [], [], [], 0
    for block in blocks:
        if not isinstance(block, dict):
            errors.append("invalid_answer_block")
            continue
        identifier, text = block.get("block_id"), block.get("text")
        refs, kind = block.get("citation_refs", []), block.get("kind", "fact")
        if not _text(identifier, 256) or identifier in ids:
            errors.append("invalid_or_duplicate_block_id")
        ids.append(identifier)
        if not _text(text, 6000):
            errors.append("invalid_block_text")
        elif isinstance(text, str):
            byte_count += len(text.encode("utf-8"))
        refs_valid = (
            isinstance(refs, list)
            and len(refs) <= 20
            and all(_text(ref, 256) for ref in refs)
        )
        if not refs_valid or len(set(refs)) != len(refs):
            errors.append("invalid_citation_refs")
        if kind == "notice":
            notices.append(block)
            if (
                text != (NOTICE_TEXTS.get(status) if isinstance(status, str) else None)
                or refs
            ):
                errors.append("invalid_status_notice")
        elif kind == "fact":
            facts.append(block)
            if not refs:
                errors.append("uncited_fact")
        else:
            errors.append("invalid_block_kind")
    if byte_count > 24000:
        errors.append("answer_text_budget_exceeded")
    if len(notices) > 1:
        errors.append("duplicate_status_notice")
    if (_in(status, SUBSTANTIVE_STATUSES) and not facts) or (
        not _in(status, SUBSTANTIVE_STATUSES) and facts
    ):
        errors.append("answer_status_block_mismatch")
    if status == "conflicting_sources":
        refs = [
            set(b.get("citation_refs", []))
            for b in facts
            if isinstance(b.get("citation_refs"), list)
            and all(isinstance(ref, str) for ref in b["citation_refs"])
        ]
        if not any(left - right and right - left for left in refs for right in refs):
            errors.append("conflict_sources_not_separately_cited")
    return sorted(set(errors))


def qa_metrics(sample: dict, artifact: dict, config: dict) -> dict:
    version = config["metric_version"]
    failed = _in(artifact.get("status"), FAILURE_STATUSES)
    completed = artifact.get("status", "completed") == "completed"
    expected = sample.get("expected_answer_status")
    expected_error = sample.get("expected_error_code")
    semantic = {
        name: not_applicable(
            "not_evaluated",
            version=version,
            evaluation_status="not_evaluated",
            reason_detail="QA semantics require an independent, calibrated or human assessment; production validation is not an evaluation judge.",
        )
        for name in ("qa_correctness", "qa_faithfulness")
    }
    output = {
        **semantic,
        "qa_answer_status_match": (
            metric(
                int(completed and artifact.get("answer_status") == expected),
                version=version,
            )
            if _in(expected, ANSWER_STATUSES)
            else not_applicable("expected_technical_failure", version=version)
        ),
        "qa_failure_behavior_match": (
            metric(
                int(
                    failed
                    and artifact.get("error_code") == expected_error
                    and not artifact.get("blocks")
                    and not artifact.get("answer_status")
                    and not artifact.get("evidence")
                    and not artifact.get("retrieval_query")
                    and not artifact.get("published_answer")
                ),
                version=version,
                details={
                    "expected_error_code": expected_error,
                    "actual_error_code": artifact.get("error_code"),
                    "requires_no_published_answer_or_source": True,
                },
            )
            if expected_error
            else not_applicable("no_expected_technical_failure", version=version)
        ),
    }
    output["qa_answer_structure_validity"] = (
        not_applicable("expected_technical_failure", version=version)
        if failed and expected_error
        else metric(
            int(completed and not structure_errors(artifact)),
            version=version,
            details={"errors": structure_errors(artifact)},
        )
    )
    if failed:
        for name in (
            "qa_citation_validity",
            "qa_fact_citation_coverage",
            "qa_evidence_group_recall",
            "qa_all_evidence_hit",
        ):
            output[name] = not_applicable("no_answer_artifact", version=version)
        return output

    raw_blocks = artifact.get("blocks")
    blocks = (
        [block for block in raw_blocks if isinstance(block, dict)]
        if isinstance(raw_blocks, list)
        else []
    )
    facts = [block for block in blocks if block.get("kind", "fact") == "fact"]
    evidence = artifact.get("evidence", [])
    counts = Counter(item.get("evidence_id") for item in evidence)
    by_id = {item.get("evidence_id"): item for item in evidence}
    provided = {item.get("evidence_id") for item in context_of(artifact)}
    sources = {source_identity(ref) for ref in sample.get("source_refs", [])}
    checks, refs = {}, []
    for block in blocks:
        citations = block.get("citation_refs", [])
        if not isinstance(citations, list):
            citations = []
        refs.extend(ref if isinstance(ref, str) else "" for ref in citations)
    for ref in refs:
        item = by_id.get(ref)
        if item is None or counts[ref] != 1 or ref not in provided:
            checks[ref] = {
                "identity": False,
                "authorized": False,
                "hash_match": False,
                "locator_match": False,
            }
        else:
            checks[ref] = {
                "identity": item.get("source_type", "document") == "document"
                and source_identity(item) in sources,
                **citation_check(item, sample, artifact),
            }

    def valid(ref):
        values = checks[ref].values()
        return (
            False
            if any(value is False for value in values)
            else None
            if any(value is None for value in values)
            else True
        )

    passed = sum(valid(ref) is True for ref in refs)
    unknown = sum(valid(ref) is None for ref in refs)
    detail = {
        "identity_valid_count": sum(checks[ref]["identity"] for ref in refs),
        "authorized_count": sum(checks[ref]["authorized"] for ref in refs),
        "hash_valid_count": sum(checks[ref]["hash_match"] for ref in refs),
        "locator_valid_count": sum(
            checks[ref]["locator_match"] is True for ref in refs
        ),
        "citation_count": len(refs),
    }
    output["qa_citation_validity"] = (
        uncertain(
            passed,
            len(refs),
            unknown,
            "source_validation_unreported",
            version=version,
            **detail,
        )
        if unknown
        else metric(passed, len(refs), version=version, details=detail)
    )
    covered, unknown_facts = 0, 0
    for block in facts:
        cited = block.get("citation_refs", [])
        if (
            not isinstance(cited, list)
            or not cited
            or not all(isinstance(ref, str) for ref in cited)
        ):
            continue
        states = [valid(ref) for ref in cited]
        covered += all(state is True for state in states)
        unknown_facts += all(state is not False for state in states) and any(
            state is None for state in states
        )
    output["qa_fact_citation_coverage"] = (
        uncertain(
            covered,
            len(facts),
            unknown_facts,
            "source_validation_unreported",
            version=version,
        )
        if unknown_facts
        else metric(covered, len(facts), version=version)
    )
    groups = sample.get("gold_evidence_groups", [])
    if not groups:
        for name in ("qa_evidence_group_recall", "qa_all_evidence_hit"):
            output[name] = not_applicable("no_gold_evidence_groups", version=version)
        return output
    cited = [by_id[ref] for ref in set(refs) if valid(ref) is True]
    unresolved = [by_id[ref] for ref in set(refs) if valid(ref) is None]
    hit, mapping_unknown = coverage(
        groups, cited, sample, artifact.get("mapping_status") == "mapping_failed"
    )
    possible, possible_unknown = coverage(groups, cited + unresolved, sample)
    unknown_groups = sorted(
        (set(mapping_unknown) | set(possible_unknown) | set(possible)) - set(hit)
    )
    detail = {
        "hit_group_ids": hit,
        "unknown_group_ids": unknown_groups,
        "coverage_rule": "complete_union_of_cited_verified_unicode_codepoint_ranges",
    }
    output["qa_evidence_group_recall"] = (
        uncertain(
            len(hit),
            len(groups),
            len(unknown_groups),
            "source_validation_unreported",
            version=version,
            **detail,
        )
        if unknown_groups
        else metric(len(hit), len(groups), version=version, details=detail)
    )
    output["qa_all_evidence_hit"] = (
        uncertain(0, 1, 1, "source_validation_unreported", version=version, **detail)
        if unknown_groups and len(hit) + len(unknown_groups) == len(groups)
        else metric(int(len(hit) == len(groups)), version=version, details=detail)
    )
    return output
