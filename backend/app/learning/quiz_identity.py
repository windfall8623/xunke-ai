"""Stable objective-question identity shared by publication and learning events.

The grading protocol, visible content and immutable cited source spans determine
identity. A new quiz/run/question/evidence ID cannot make reused content new.
"""

import unicodedata

from app.rag.contracts import ArtifactQuestion, EvidencePack, stable_hash


def _text(value: str) -> str:
    return unicodedata.normalize("NFC", value.replace("\r\n", "\n")).strip()


def _citation_identity(evidence):
    locator = evidence.locator.model_dump(mode="json")
    for field in ("section_ids", "block_ids"):
        if field in locator:
            locator[field] = sorted(set(locator[field]))
    if evidence.source_type == "document":
        return {
            "source_type": "document",
            "owner_id": evidence.owner_id,
            "namespace": evidence.namespace,
            "doc_id": evidence.doc_id,
            "document_version_id": evidence.document_version_id,
            "parse_artifact_id": evidence.parse_artifact_id,
            "index_build_id": evidence.index_build_id,
            "locator": locator,
        }
    return {
        "source_type": "web",
        "url": evidence.url,
        "snapshot_hash": evidence.snapshot_hash,
        "locator": locator,
    }


def canonical_quiz_question_version(question, evidence_pack) -> str:
    """Hash content and grading with temporary citation IDs resolved to sources.

    Accept a persisted ArtifactQuestion or its strict DTO shape. API image state
    is removed by the caller when verifying the stored quiz projection. Unknown
    and ambiguous citation IDs are rejected instead of silently losing evidence.
    Feedback wording, labels, difficulty and support-quote presentation do not
    make an otherwise identical question new; the artifact reader checks them.
    """
    question = ArtifactQuestion.model_validate(question)
    pack = EvidencePack.model_validate(evidence_pack)
    by_id = {}
    for evidence in pack.evidence:
        identity = _citation_identity(evidence)
        if evidence.evidence_id in by_id and by_id[evidence.evidence_id] != identity:
            raise ValueError("Ambiguous citation identity")
        by_id[evidence.evidence_id] = identity
    citations = {}
    for reference in question.citation_refs:
        if reference not in by_id:
            raise ValueError("Unknown citation identity")
        identity = by_id[reference]
        citations[stable_hash(identity)] = identity
    return stable_hash(
        {
            "protocol": "objective-question-v1",
            "grading": "exact-option-set-v1",
            "type": question.type,
            "stem": _text(question.stem),
            "options": [
                {"key": option.key, "text": _text(option.text)}
                for option in sorted(question.options, key=lambda item: item.key)
            ],
            "answer": sorted(set(question.answer)),
            "citations": [citations[key] for key in sorted(citations)],
        }
    )
