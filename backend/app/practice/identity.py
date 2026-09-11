"""Stable question identities shared by artifact validation and later graders.

Temporary question/evidence IDs and retrieval metadata are not learning novelty.
The caller supplies validated inputs; source authorization remains a service step.
"""

from __future__ import annotations

import json
import unicodedata
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.rag.contracts import DocumentEvidence, EvidencePack, stable_hash

if TYPE_CHECKING:
    from app.practice.contracts import PracticeQuestion


def normalize_cloze_text(value: str, normalization: str) -> str:
    """Apply the declared, frozen cloze scoring normalization."""
    normalized = " ".join(unicodedata.normalize("NFKC", value).split())
    if normalization == "nfkc-space-casefold-v1":
        return normalized.casefold()
    if normalization == "nfkc-space-v1":
        return normalized
    raise ValueError("Unknown cloze normalization")


def _canonical_values(value: Any) -> Any:
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        sign, coefficient, exponent = value.as_tuple()
        digits = list(coefficient)
        while digits[-1] == 0:
            digits.pop()
            exponent += 1
        # Tuple construction is exact even under a caller's low Decimal precision.
        return str(Decimal((sign, tuple(digits), exponent)))
    if isinstance(value, dict):
        return {key: _canonical_values(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_values(item) for item in value]
    return value


def _source_identity(evidence: DocumentEvidence) -> dict:
    locator = evidence.locator.model_dump(mode="json")
    locator["block_ids"] = sorted(set(locator["block_ids"]))
    locator["section_ids"] = sorted(set(locator["section_ids"]))
    return {
        "doc_id": evidence.doc_id,
        "document_version_id": evidence.document_version_id,
        "parse_artifact_id": evidence.parse_artifact_id,
        "index_build_id": evidence.index_build_id,
        "locator": locator,
    }


def canonical_question_version(
    question: PracticeQuestion, evidence_pack: EvidencePack
) -> str:
    """Hash question content and scoring rules against immutable source anchors."""
    by_id = {}
    for evidence in evidence_pack.evidence:
        if not isinstance(evidence, DocumentEvidence):
            raise ValueError("Practice identities require document evidence")
        if evidence.evidence_id in by_id:
            raise ValueError("Duplicate evidence identity")
        by_id[evidence.evidence_id] = _source_identity(evidence)

    def fixed_sources(references: list[str]) -> list[dict]:
        sources = {}
        for reference in references:
            if reference not in by_id:
                raise ValueError("Question refers to missing evidence")
            source = by_id[reference]
            key = json.dumps(
                source, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            sources[key] = source
        return [sources[key] for key in sorted(sources)]

    # Novelty covers content and scoring only. Full artifacts retain presentation
    # and concept bindings; rubric checksums retain the complete rubric.
    if question.type == "cloze":
        rubric = {
            "version": question.rubric.version,
            "normalization": question.rubric.normalization,
            "slots": [
                {
                    "blank_id": slot.blank_id,
                    "accepted": sorted(
                        normalize_cloze_text(answer, question.rubric.normalization)
                        for answer in slot.accepted
                    ),
                    "weight": slot.weight,
                }
                for slot in sorted(
                    question.rubric.slots, key=lambda slot: slot.blank_id
                )
            ],
        }
    elif question.type == "numeric":
        rubric = {
            "version": question.rubric.version,
            "target": question.rubric.target,
            "absolute_tolerance": question.rubric.absolute_tolerance,
            "relative_tolerance": question.rubric.relative_tolerance,
            "unit": question.rubric.unit,
            "unit_aliases": sorted(question.rubric.unit_aliases),
        }
    else:
        rubric = {
            "version": question.rubric.version,
            "reference_answer": question.rubric.reference_answer,
            "criteria": [
                {
                    "criterion_id": criterion.criterion_id,
                    "reference_point": criterion.reference_point,
                    "weight": criterion.weight,
                    "evidence_refs": fixed_sources(criterion.evidence_refs),
                }
                for criterion in sorted(
                    question.rubric.criteria,
                    key=lambda criterion: criterion.criterion_id,
                )
            ],
        }
    content = {
        "type": question.type,
        "stem": question.stem,
        "citation_refs": fixed_sources(question.citation_refs),
        "rubric": rubric,
    }
    return stable_hash(_canonical_values(content))
