"""Pure applicability checks for a supplied practice grader approval profile.

The caller loads a trusted read-only approval artifact and derives the expected
identity from frozen grading inputs. This module neither grants approval nor
authenticates reviewers, and publication must revalidate the current approval.
"""

from datetime import datetime
import re

from app.rag.contracts import stable_hash


_IDENTITY_FIELDS = (
    "model_fingerprint",
    "prompt_hash",
    "grader_version",
    "rubric_family",
    "rubric_version",
)
_PROFILE_FIELDS = {
    "schema_version",
    "profile_id",
    "profile_hash",
    "enabled",
    "scope",
    "calibration_record",
    *_IDENTITY_FIELDS,
}
_APPROVAL_FIELDS = {
    "decision",
    "reviewer_id",
    "reviewed_at",
    "dataset_hash",
    "report_hash",
    "protocol_hash",
}
_QUESTION_TYPES = {"cloze", "numeric", "short_answer"}
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_hash(value) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _is_scope_list(value) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_is_text(item) for item in value)
    )


def _is_reviewed_at(value) -> bool:
    if not _is_text(value):
        return False
    try:
        reviewed_at = datetime.fromisoformat(value)
    except ValueError:
        return False
    return reviewed_at.utcoffset() is not None


def calibration_profile_applies(profile: dict | None, expected_identity: dict) -> bool:
    """Accept only an enabled, intact approval matching every scoring identity."""
    if not isinstance(profile, dict) or set(profile) != _PROFILE_FIELDS:
        return False
    if not isinstance(expected_identity, dict):
        return False
    if (
        profile["schema_version"] != "practice-grader-profile.v1"
        or profile["enabled"] is not True
        or not _is_text(profile["profile_id"])
        or not _is_hash(profile["profile_hash"])
    ):
        return False
    if not all(_is_text(profile[field]) for field in _IDENTITY_FIELDS):
        return False
    if not all(
        _is_text(expected_identity.get(field))
        for field in (*_IDENTITY_FIELDS, "question_type", "language")
    ):
        return False
    if not _is_hash(profile["prompt_hash"]) or not _is_hash(
        expected_identity["prompt_hash"]
    ):
        return False

    scope = profile["scope"]
    if not isinstance(scope, dict) or set(scope) != {"question_types", "languages"}:
        return False
    if not all(
        _is_scope_list(scope[field]) for field in ("question_types", "languages")
    ):
        return False
    if not set(scope["question_types"]).issubset(_QUESTION_TYPES):
        return False

    record = profile["calibration_record"]
    if not isinstance(record, dict) or set(record) != _APPROVAL_FIELDS:
        return False
    if (
        record["decision"] != "approved"
        or not _is_text(record["reviewer_id"])
        or not _is_reviewed_at(record["reviewed_at"])
        or not all(
            _is_hash(record[field])
            for field in ("dataset_hash", "report_hash", "protocol_hash")
        )
    ):
        return False

    payload = {key: value for key, value in profile.items() if key != "profile_hash"}
    try:
        profile_hash = stable_hash(payload)
    except UnicodeEncodeError:
        return False
    if profile_hash != profile["profile_hash"]:
        return False
    return (
        all(profile[field] == expected_identity[field] for field in _IDENTITY_FIELDS)
        and expected_identity["question_type"] in scope["question_types"]
        and expected_identity["language"] in scope["languages"]
    )
