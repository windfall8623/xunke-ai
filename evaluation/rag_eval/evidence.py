"""Exact Unicode source-span coverage, independent of retrieval chunk IDs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from .contracts import sha256_text


def source_identity(value: dict) -> tuple:
    locator = value.get("locator", {})

    def get(key, *aliases):
        for name in (key, *aliases):
            if value.get(name) is not None:
                return str(value[name])
            if locator.get(name) is not None:
                return str(locator[name])
        return None

    return (
        get("doc_id", "document_id"),
        get(
            "source_version_id",
            "document_version_id",
            "source_version",
            "version_id",
            "version",
        ),
        get("parse_artifact_id"),
        get("canonical_text_hash"),
    )


def span_identity(span: dict) -> tuple:
    # Offsets are global in one immutable canonical text. A retrieval chunk may
    # cross several paragraph blocks; its first block_id cannot restrict coverage
    # to that paragraph. block_id remains a locator/audit field, not a chunk gate.
    return source_identity(span)


def valid_range(span: dict) -> bool:
    start, end = span.get("start_char"), span.get("end_char")
    return (
        type(start) is int
        and type(end) is int
        and 0 <= start < end
        and all(v is not None for v in source_identity(span))
        and bool(span.get("block_id"))
    )


def evidence_spans(evidence: dict) -> list[dict]:
    if evidence.get("source_type", "document") != "document":
        return []
    inherited = dict(
        zip(
            ("doc_id", "source_version_id", "parse_artifact_id", "canonical_text_hash"),
            source_identity(evidence),
        )
    )
    spans = evidence.get("spans") or [evidence.get("locator", {})]
    return [{**inherited, **span} for span in spans]


def merge_ranges(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def allowed_evidence(evidence: dict, sample: dict) -> bool:
    if (
        evidence.get("authorized") is False
        or evidence.get("mapping_status") == "unauthorized"
    ):
        return False
    identity = source_identity(evidence)
    refs = sample.get("source_refs", [])
    if not refs:
        return evidence.get("authorized") is True
    matching = [ref for ref in refs if source_identity(ref)[:2] == identity[:2]]
    if not matching:
        return False
    for ref in matching:
        if ref.get("revoked") or ref.get("authorization_status") in {
            "revoked",
            "denied",
        }:
            continue
        if ref.get("namespace") and ref["namespace"] != evidence.get("namespace"):
            continue
        if ref.get("owner_id") is not None and str(ref["owner_id"]) != str(
            evidence.get("owner_id")
        ):
            continue
        ranges = ref.get("allowed_spans") or sample.get("scope", {}).get(
            "allowed_spans"
        )
        if ranges:
            allowed = span_ranges(ranges)
            if not all(is_covered(span, allowed) for span in evidence_spans(evidence)):
                continue
        return True
    return False


def span_ranges(spans: Iterable[dict]) -> dict[tuple, list[tuple[int, int]]]:
    ranges: dict[tuple, list[tuple[int, int]]] = defaultdict(list)
    for span in spans:
        if valid_range(span):
            ranges[span_identity(span)].append((span["start_char"], span["end_char"]))
    return {key: merge_ranges(value) for key, value in ranges.items()}


def provided_ranges(evidence: list[dict], sample: dict) -> dict:
    accepted = []
    for item in evidence:
        if not allowed_evidence(item, sample):
            continue
        checks = citation_check(item, sample, {})
        if checks["hash_match"] is False or checks["locator_match"] is False:
            continue
        accepted.extend(evidence_spans(item))
    return span_ranges(accepted)


def is_covered(span: dict, ranges: dict) -> bool:
    if not valid_range(span):
        return False
    return any(
        start <= span["start_char"] and end >= span["end_char"]
        for start, end in ranges.get(span_identity(span), [])
    )


def group_spans(group: dict) -> list[list[dict]]:
    alternatives = group.get("alternatives", group.get("evidence_alternatives", []))
    return [
        alt if isinstance(alt, list) else alt.get("spans", []) for alt in alternatives
    ]


def coverage(
    groups: list[dict], evidence: list[dict], sample: dict, mapping_failed: bool = False
) -> tuple[list[str], list[str]]:
    ranges = provided_ranges(evidence, sample)
    provided_ids = {
        source_identity(item) for item in evidence if allowed_evidence(item, sample)
    }
    hit, unknown = [], []
    for index, group in enumerate(groups):
        gid = str(group.get("group_id", index))
        alternatives = group_spans(group)
        if any(
            spans and all(is_covered(span, ranges) for span in spans)
            for spans in alternatives
        ):
            hit.append(gid)
            continue
        has_mismatch = any(
            actual[:2] == source_identity(span)[:2]
            and actual[2:] != source_identity(span)[2:]
            for spans in alternatives
            for span in spans
            for actual in provided_ids
        )
        if (
            mapping_failed
            or has_mismatch
            or any(not valid_range(span) for spans in alternatives for span in spans)
        ):
            unknown.append(gid)
    return hit, unknown


def candidates_of(artifact: dict) -> list[dict]:
    pack = artifact.get("evidence_pack", {})
    return (
        artifact.get("candidates", artifact.get("evidence", pack.get("evidence", [])))
        or []
    )


def context_of(artifact: dict) -> list[dict]:
    if "context_evidence" in artifact:
        return artifact["context_evidence"] or []
    pack = artifact.get("evidence_pack", {})
    evidence = artifact.get("evidence", pack.get("evidence", [])) or []
    ids = artifact.get(
        "context_evidence_ids",
        pack.get("provided_evidence_ids", pack.get("context_evidence_ids")),
    )
    if ids is None:
        return evidence
    by_id = {
        item.get("evidence_id"): item for item in evidence + candidates_of(artifact)
    }
    return [by_id[eid] for eid in ids if eid in by_id]


def redundancy(evidence: list[dict], sample: dict) -> tuple[int, int]:
    spans = [
        span
        for item in evidence
        if allowed_evidence(item, sample)
        for span in evidence_spans(item)
        if valid_range(span)
    ]
    total = sum(span["end_char"] - span["start_char"] for span in spans)
    unique = sum(
        end - start for ranges in span_ranges(spans).values() for start, end in ranges
    )
    return total - unique, total


def authoritative_texts(sample: dict, artifact: dict) -> dict:
    result = {}
    for source in sample.get("source_refs", []) + artifact.get("source_texts", []):
        text = source.get("canonical_text", source.get("text"))
        if isinstance(text, str) and sha256_text(text) == source_identity(source)[3]:
            result[source_identity(source)] = text
    return result


def citation_check(
    evidence: dict, sample: dict, artifact: dict
) -> dict[str, bool | None]:
    if evidence.get("source_type", "document") != "document":
        excerpt = evidence.get("excerpt", "")
        return {
            "authorized": bool(evidence.get("authorized")),
            "hash_match": sha256_text(excerpt) == evidence.get("text_hash"),
            "locator_match": None,
        }
    spans = evidence_spans(evidence)
    excerpt = evidence.get("excerpt", "")
    hash_match = isinstance(excerpt, str) and sha256_text(excerpt) == evidence.get(
        "text_hash"
    )
    if len(spans) == 1:
        hash_match = hash_match and spans[0].get("quote_hash") == sha256_text(excerpt)
    texts = authoritative_texts(sample, artifact)
    locator_match: bool | None = True
    for span in spans:
        if not valid_range(span):
            locator_match = False
            break
        text = texts.get(source_identity(span))
        if text is None:
            observations = artifact.get("source_validation", [])
            observation = next(
                (
                    item
                    for item in observations
                    if item.get("evidence_id") == evidence.get("evidence_id")
                    and source_identity(item) == source_identity(span)
                    and item.get("start_char") == span["start_char"]
                    and item.get("end_char") == span["end_char"]
                    and item.get("quote_hash") == span.get("quote_hash")
                ),
                None,
            )
            if (
                observation is not None
                and type(observation.get("locator_valid")) is bool
            ):
                locator_match = (
                    observation["locator_valid"]
                    if locator_match is not False
                    else False
                )
            elif locator_match is not False:
                locator_match = None
            continue
        quote = text[span["start_char"] : span["end_char"]]
        valid = span["end_char"] <= len(text) and sha256_text(quote) == span.get(
            "quote_hash"
        )
        if len(spans) == 1:
            valid = valid and quote == excerpt
        if not valid:
            locator_match = False
    return {
        "authorized": allowed_evidence(evidence, sample),
        "hash_match": bool(hash_match),
        "locator_match": locator_match,
    }
