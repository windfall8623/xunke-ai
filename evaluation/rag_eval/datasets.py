"""Dataset integrity, source anchoring, connected splits, and actual review records."""

from __future__ import annotations

import copy
import hashlib
import heapq
import json
import math
import os
import re
import unicodedata
import zlib
from collections import Counter, defaultdict
from decimal import Decimal, DecimalException
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator

from .contracts import CASE_TYPES, LEARNING_CASE_TYPES, canonical_hash, sha256_text
from .evidence import group_spans, source_identity, valid_range
from .quiz_rubric import REQUIRED_SEMANTICS


@lru_cache(maxsize=4)
def _learning_validator(
    case_type: str, schema_name: str = "EvalSample"
) -> Draft202012Validator:
    # This is the canonical backend export, not a second private question schema.
    root = Path(
        os.environ.get(
            "EVAL_CONTRACTS_DIR", Path(__file__).resolve().parents[2] / "contracts"
        )
    )
    path = root / f"{schema_name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    reference = schema["discriminator"]["mapping"][case_type]
    return Draft202012Validator({"$ref": reference, "$defs": schema["$defs"]})


def validate_saved_learning_artifact(artifact: dict) -> None:
    """Validate offline envelopes against the same exported contract as the API."""
    kind = artifact.get("case_type")
    if kind not in LEARNING_CASE_TYPES:
        return
    canonical_hash(artifact)
    try:
        validator = _learning_validator(kind, "EvaluationArtifact")
    except (OSError, KeyError, ValueError) as exc:
        raise ValueError(
            "canonical learning EvaluationArtifact schema is unavailable; export contracts first"
        ) from exc
    if next(validator.iter_errors(artifact), None) is not None:
        raise ValueError("saved learning artifact does not match the canonical schema")


def _learning_sample_errors(sample: dict) -> list[str]:
    kind = sample["case_type"]
    try:
        canonical_hash(sample)
    except (TypeError, ValueError):
        return ["sample_not_finite_json"]
    try:
        validator = _learning_validator(kind)
    except (OSError, KeyError, ValueError) as exc:
        raise ValueError(
            "canonical learning EvalSample schema is unavailable; export contracts first"
        ) from exc
    if next(validator.iter_errors(sample), None) is not None:
        return ["invalid_learning_sample_schema"]
    errors = []
    error = sample.get("expected_error_code")
    if error is not None and not error.strip():
        errors.append("expected_error_code_blank")
    if kind == "practice_generation":
        expected = sample["expected_outcome"]
        if (expected == "failed" and not error) or (expected == "generate" and error):
            errors.append("invalid_practice_expectation")
        spec = sample["spec"]
        if (
            len(spec["objectives"]) != len(spec["concept_ids"])
            or len("；".join(spec["objectives"])) > 2000
            or any(not item.strip() for item in spec["objectives"])
            or len(spec["concept_ids"]) != len(set(spec["concept_ids"]))
            or len(spec["question_types"]) != len(set(spec["question_types"]))
        ):
            errors.append("invalid_practice_spec")
        semantics = sample.get("generation_rubric", {}).get(
            "required_semantics", REQUIRED_SEMANTICS
        )
        if len(semantics) != len(REQUIRED_SEMANTICS) or set(semantics) != set(
            REQUIRED_SEMANTICS
        ):
            errors.append("invalid_generation_review_criteria")
    else:
        if (
            sample["question_type"] != sample["question"]["type"]
            or sample["question_type"] != sample["answer"]["type"]
        ):
            errors.append("grading_question_answer_type_mismatch")
        if error is not None and sample["expected_grade_status"] not in {
            "failed",
            "cancelled",
        }:
            errors.append("invalid_grading_expectation")
        reference = sample.get("reference_grade")
        if reference:
            score = reference.get("score")
            if reference["status"] != "graded" and score is not None:
                errors.append("unresolved_reference_has_score")
            if score is not None:
                try:
                    exact = Decimal(score)
                    valid = exact.is_finite() and 0 <= exact <= 1
                except DecimalException:
                    valid = False
                if not valid:
                    errors.append("invalid_reference_score")
        answer = sample["answer"]
        if answer["type"] == "numeric":
            try:
                number = Decimal(answer["value"])
                valid = (
                    re.fullmatch(
                        r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?",
                        answer["value"],
                    )
                    and number.is_finite()
                    and -100 <= number.adjusted() <= 100
                )
            except DecimalException:
                valid = False
            if not valid:
                errors.append("invalid_numeric_answer")
    return errors


def _text_sketch(text: str, *, size: int = 256) -> set[int]:
    """Bounded, deterministic bottom-k character shingle sketch.

    Long sources use 16 evenly distributed 4K windows. This catches strong
    copies cheaply; it does not replace a human audit of related editions.
    """
    starts = (
        [0]
        if len(text) <= 65536
        else sorted({(len(text) - 4096) * index // 15 for index in range(16)})
    )
    selected, heap = set(), []
    for start in starts:
        window = text[start : start + (65536 if len(starts) == 1 else 4096)]
        for index in range(max(0, len(window) - 4)):
            value = zlib.crc32(window[index : index + 5].encode("utf-8"))
            if value in selected:
                continue
            if len(selected) < size:
                selected.add(value)
                heapq.heappush(heap, -value)
            elif value < -heap[0]:
                selected.remove(-heapq.heapreplace(heap, -value))
                selected.add(value)
    return selected


def _source_similarity(sources, source_texts):
    summaries = []
    for identity, source in sources.items():
        text = source_texts.get(identity)
        if text is None or not source.get("family_id"):
            continue
        normalized = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
        summaries.append(
            {
                "doc_id": source["doc_id"],
                "family_id": source["family_id"],
                "length": len(normalized),
                "hash": sha256_text(normalized),
                "sketch": _text_sketch(normalized),
            }
        )
    pairs = []
    for index, left in enumerate(summaries):
        for right in summaries[index + 1 :]:
            if left["hash"] == right["hash"] and left["length"]:
                reason, similarity = "identical_normalized_text", 1.0
            elif (
                min(left["length"], right["length"]) >= 40
                and min(left["length"], right["length"])
                / max(left["length"], right["length"])
                >= 0.85
            ):
                union = sorted(left["sketch"] | right["sketch"])[:256]
                similarity = (
                    sum(
                        value in left["sketch"] and value in right["sketch"]
                        for value in union
                    )
                    / len(union)
                    if union
                    else 0
                )
                if similarity < 0.90:
                    continue
                reason = "near_duplicate_text"
            else:
                continue
            pairs.append(
                {
                    "doc_ids": [left["doc_id"], right["doc_id"]],
                    "family_ids": [left["family_id"], right["family_id"]],
                    "reason": reason,
                    "estimated_jaccard": similarity,
                }
            )
    return {
        "version": "normalized-char5-bottom256-v1",
        "audited_source_count": len(summaries),
        "near_duplicate_threshold": 0.90,
        "connected_pairs": pairs,
        "limitations": "A bounded lexical copy audit; translations, related editions, paraphrases, and shared chapters still require the family_split human checklist.",
    }


def contained_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise ValueError("dataset path must be a nonempty relative path")
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("dataset path escapes its manifest directory")
    return path


def load_dataset(path: str | Path) -> tuple[dict, list[dict]]:
    path = Path(path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    root = path.parent
    for relative, expected in manifest.get("file_checksums", {}).items():
        actual = hashlib.sha256(contained_path(root, relative).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"dataset file checksum mismatch: {relative}")
    source_texts = {}
    for source in manifest.get("sources", []):
        text_path = source.get("canonical_text_path")
        if text_path:
            text = contained_path(root, text_path).read_text(encoding="utf-8")
            if sha256_text(text) != source.get("canonical_text_hash"):
                raise ValueError("canonical text checksum mismatch")
            source_texts[source_identity(source)] = text
    files = manifest.get("sample_files", {})
    if isinstance(files, list):
        files = {str(index): value for index, value in enumerate(files)}
    samples = []
    for relative in files.values():
        for line in (
            contained_path(root, relative).read_text(encoding="utf-8-sig").splitlines()
        ):
            if not line.strip():
                continue
            sample = json.loads(line)
            for ref in sample.get("source_refs", []):
                if source_identity(ref) in source_texts:
                    ref["canonical_text"] = source_texts[source_identity(ref)]
            samples.append(sample)
    hydrated = copy.deepcopy(manifest)
    for source in hydrated.get("sources", []):
        if source_identity(source) in source_texts:
            source["canonical_text"] = source_texts[source_identity(source)]
    return hydrated, samples


def validate_dataset(
    manifest: dict,
    samples: list[dict],
    *,
    require_frozen: bool = False,
    allow_single_review_freeze: bool = False,
) -> dict:
    errors, warnings = [], []

    def issue(target, code, sample_id=None, detail=None):
        item = {"code": code}
        if sample_id:
            item["sample_id"] = sample_id
        if detail:
            item["detail"] = detail
        target.append(item)

    if manifest.get("state") not in {"draft", "reviewed", "frozen"}:
        issue(errors, "invalid_dataset_state")
    if require_frozen and manifest.get("state") != "frozen":
        issue(errors, "dataset_not_frozen")
    if not samples:
        issue(errors, "empty_dataset")
    sources = {
        source_identity(source): source for source in manifest.get("sources", [])
    }
    if len(sources) != len(manifest.get("sources", [])):
        issue(errors, "duplicate_source_identity")
    source_texts = {}
    for key, source in sources.items():
        if not all(key) or not source.get("source_sha256") or not source.get("license"):
            issue(errors, "source_provenance_incomplete", detail=source.get("doc_id"))
        if source.get("revoked") or source.get("authorization_status") == "revoked":
            issue(errors, "source_revoked", detail=source.get("doc_id"))
        text = source.get("canonical_text")
        if isinstance(text, str):
            if sha256_text(text) != key[3]:
                issue(
                    errors, "canonical_text_hash_mismatch", detail=source.get("doc_id")
                )
            else:
                source_texts[key] = text
    seen_ids, family_parent, sample_families, sample_splits = set(), {}, {}, {}

    def find(family):
        family_parent.setdefault(family, family)
        if family_parent[family] != family:
            family_parent[family] = find(family_parent[family])
        return family_parent[family]

    similarity_audit = _source_similarity(sources, source_texts)
    for pair in similarity_audit["connected_pairs"]:
        left, right = [find(family) for family in pair["family_ids"]]
        family_parent[max(left, right)] = min(left, right)
    if similarity_audit["connected_pairs"]:
        issue(warnings, "text_similarity_families_connected")
    human_count = second_count = disputed_count = disputed_second = 0
    ordinary_count = ordinary_second = 0
    case_counts = Counter()
    for sample in samples:
        sid = sample.get("sample_id")
        if not isinstance(sid, str) or not sid or sid in seen_ids:
            issue(errors, "invalid_or_duplicate_sample_id", sid)
        seen_ids.add(sid)
        kind = sample.get("case_type")
        case_counts[kind] += 1
        if kind not in CASE_TYPES:
            issue(errors, "invalid_case_type", sid)
            continue
        if kind in LEARNING_CASE_TYPES:
            for code in _learning_sample_errors(sample):
                issue(errors, code, sid)
        if sample.get("split") not in {"dev", "judge_calibration", "locked_test"}:
            issue(errors, "invalid_split", sid)
        families = sample.get("family_ids") or (
            [sample["family_id"]] if sample.get("family_id") else []
        )
        if not families or not all(isinstance(item, str) and item for item in families):
            issue(errors, "family_identity_missing", sid)
            families = [f"missing:{sid}"]
        families = sorted(set(families))
        for family in families:
            root_a, root_b = find(families[0]), find(family)
            family_parent[max(root_a, root_b)] = min(root_a, root_b)
        sample_families[sid] = families
        sample_splits[sid] = sample.get("split")
        for ref in sample.get("source_refs", []):
            key = source_identity(ref)
            if key not in sources:
                issue(errors, "unregistered_source_reference", sid)
            elif sources[key].get("family_id") not in families:
                issue(errors, "source_family_omitted", sid)
            text = ref.get("canonical_text")
            if isinstance(text, str) and sha256_text(text) == key[3]:
                source_texts[key] = text
        if kind == "retrieval" and not sample.get("query"):
            issue(errors, "retrieval_query_missing", sid)
        if kind == "qa":
            from .qa import validate_qa_sample

            for code in validate_qa_sample(sample):
                issue(errors, code, sid)
        if kind == "quiz":
            if sample.get("question_count") not in range(3, 11):
                issue(errors, "question_count_out_of_range", sid)
            if sample.get("expected_outcome") not in {"generate", "refuse"}:
                issue(errors, "invalid_expected_quiz_outcome", sid)
            if (
                sample.get("expected_outcome") == "generate"
                and sample.get("source_sufficient") is not True
            ):
                issue(
                    errors if manifest.get("state") == "frozen" else warnings,
                    "requested_count_sufficiency_unreviewed",
                    sid,
                )
        if kind == "policy":
            if sample.get("harness", {}).get("synthetic_only") is not True:
                issue(errors, "policy_requires_synthetic_harness", sid)
            for resource in sample.get("harness", {}).get("resources", []):
                if (
                    resource.get("synthetic") is not True
                    or resource.get("namespace") == "production"
                ):
                    issue(errors, "policy_production_resource_forbidden", sid)
        groups = sample.get("gold_evidence_groups", [])
        if (
            kind == "retrieval"
            and sample.get("expected_outcome") == "answerable"
            and not groups
        ):
            issue(errors, "answerable_retrieval_gold_missing", sid)
        all_spans = []
        group_ids = set()
        for group in groups:
            if not group.get("group_id") or group["group_id"] in group_ids:
                issue(errors, "invalid_or_duplicate_gold_group", sid)
            group_ids.add(group.get("group_id"))
            alternatives = group_spans(group)
            if not alternatives or any(not alternative for alternative in alternatives):
                issue(errors, "empty_gold_alternative", sid)
            all_spans.extend(
                span for alternative in alternatives for span in alternative
            )
        for unit in sample.get("ranking_labels", []):
            if unit.get("grade") not in (0, 1, 2, 3):
                issue(warnings, "ranking_unit_unjudged", sid)
            all_spans.extend(unit.get("spans", []))
        for rubric in sample.get("question_rubrics", []):
            all_spans.extend(rubric.get("supporting_spans", []))
            all_spans.extend(rubric.get("refutation_spans", []))
        for span in all_spans:
            if not valid_range(span) or not span.get("quote_hash"):
                issue(errors, "invalid_gold_span", sid)
                continue
            key = source_identity(span)
            if key not in sources:
                issue(errors, "gold_source_unregistered", sid)
                continue
            text = source_texts.get(key)
            if text is None:
                issue(warnings, "canonical_text_unavailable_for_gold_audit", sid)
            elif (
                span["end_char"] > len(text)
                or sha256_text(text[span["start_char"] : span["end_char"]])
                != span["quote_hash"]
            ):
                issue(errors, "gold_quote_hash_mismatch", sid)
        annotation = sample.get("annotation", {})
        records = [
            record
            for record in annotation.get("review_records", [])
            if record.get("decision") == "approved"
            and record.get("reviewer_id")
            and record.get("reviewed_at")
            and record.get("provenance", "human") == "human"
        ]
        reviewers = {record["reviewer_id"] for record in records}
        independent = {
            record["reviewer_id"]
            for record in records
            if record.get("independent") is True
        }
        has_primary, has_second = bool(reviewers), len(independent) >= 2
        human_count += has_primary
        second_count += has_second
        if annotation.get("disputed"):
            disputed_count += 1
            disputed_second += has_second
        else:
            ordinary_count += 1
            ordinary_second += has_second
    clusters, splits = defaultdict(list), defaultdict(set)
    for sid, families in sample_families.items():
        root = find(families[0])
        clusters[root].append(sid)
        splits[root].add(sample_splits[sid])
    if any(len(values) > 1 for values in splits.values()):
        issue(errors, "cluster_split_leakage")
    review_target = errors if manifest.get("state") == "frozen" else warnings
    if human_count < len(samples):
        issue(review_target, "human_review_incomplete")
    secondary_complete = (
        disputed_second == disputed_count
        and ordinary_second >= math.ceil(ordinary_count * 0.2)
    )
    if not secondary_complete:
        issue(
            warnings if allow_single_review_freeze else review_target,
            "independent_second_review_incomplete",
        )
    checklist = manifest.get("review", {}).get("checklist", {})
    checklist_complete = all(
        checklist.get(key) is True
        for key in ("source_rights", "spans", "family_split", "answerability")
    ) and (
        checklist.get("second_review") is True
        or allow_single_review_freeze
        and checklist.get("second_review") is False
    )
    if not checklist_complete:
        issue(review_target, "freeze_checklist_incomplete")
    source_audit_complete = not any(
        item["code"]
        in {
            "canonical_text_unavailable_for_gold_audit",
            "requested_count_sufficiency_unreviewed",
        }
        for item in warnings
    )
    primary_complete = bool(samples) and human_count == len(samples)
    freezable = (
        not errors
        and primary_complete
        and (secondary_complete or allow_single_review_freeze)
        and checklist_complete
        and source_audit_complete
    )
    counts = {
        "retrieval": case_counts["retrieval"],
        "quiz": case_counts["quiz"],
        "qa": case_counts["qa"],
        "policy": case_counts["policy"],
        "practice_generation": case_counts["practice_generation"],
        "answer_grading": case_counts["answer_grading"],
        "samples": len(samples),
        "source_documents": len(sources),
        "families": len(family_parent),
        "clusters": len(clusters),
    }
    if manifest.get("counts"):
        for key, value in manifest["counts"].items():
            if key in counts and counts[key] != value:
                issue(errors, "manifest_count_mismatch", detail=key)
    return {
        "valid": not errors,
        "freezable": freezable and not errors,
        "state": manifest.get("state"),
        "counts": counts,
        "errors": errors,
        "warnings": warnings,
        "clusters": dict(clusters),
        "source_similarity_audit": similarity_audit,
        "review": {
            "human_reviewed_count": human_count,
            "independently_double_reviewed_count": second_count,
            "disputed_count": disputed_count,
            "disputed_double_reviewed_count": disputed_second,
            "ordinary_required_second_review": math.ceil(ordinary_count * 0.2),
        },
        "dataset_content_hash": canonical_hash(
            {"sources": sorted(sources), "samples": samples}
        ),
        "formal_gold_eligible": bool(
            freezable
            and not errors
            and secondary_complete
            and checklist.get("second_review") is True
        ),
        "release_gold_status": (
            "provisional_single_review"
            if freezable
            and (not secondary_complete or checklist.get("second_review") is False)
            else "human_reviewed"
            if freezable
            else "draft_not_release_gold"
        ),
    }
