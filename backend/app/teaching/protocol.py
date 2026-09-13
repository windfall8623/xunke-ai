"""Explicit version dispatch and public allowlists; reading never rewrites a draft."""

from typing import Literal

from pydantic import BaseModel

from app.core.values import digest, dump
from app.teaching.contracts import CourseDraft, LessonBlock, LessonCheck, LessonDraft, TeachUnit
from app.teaching.contracts_v2 import CourseDraftV2, LessonDraftV2, TeachUnitV2

V1 = "xunke-teach.v1"
V2 = "xunke-teach.v2"
HISTORICAL_V1 = "zhixue-teach.v1"


class _HistoricalCourseDraft(CourseDraft):
    """Read the exact deployed v1 envelope without canonicalizing its identity."""

    schema_version: Literal["zhixue-teach.v1"] = HISTORICAL_V1


class _HistoricalLessonDraft(LessonDraft):
    schema_version: Literal["zhixue-teach.v1"] = HISTORICAL_V1


def _model(version, v1, v2):
    if version == V1:
        return v1
    if version == HISTORICAL_V1:
        # Only this known historical marker is accepted. V1 validation, source
        # checks and extra-field rejection stay intact; dumps retain its marker.
        return {CourseDraft: _HistoricalCourseDraft, LessonDraft: _HistoricalLessonDraft}.get(v1, v1)
    if version == V2:
        return v2
    raise ValueError("unsupported_teach_schema_version")


def parse_course_draft(raw: dict) -> CourseDraft | CourseDraftV2:
    return _model(raw.get("schema_version"), CourseDraft, CourseDraftV2).model_validate(raw)


def parse_lesson_draft(raw: dict) -> LessonDraft | LessonDraftV2:
    return _model(raw.get("schema_version"), LessonDraft, LessonDraftV2).model_validate(raw)


def parse_teach_unit(raw: dict, *, schema_version: str) -> TeachUnit | TeachUnitV2:
    return _model(schema_version, TeachUnit, TeachUnitV2).model_validate(raw)


def public_unit(raw: dict, *, schema_version: str) -> dict:
    unit = parse_teach_unit(raw, schema_version=schema_version).model_dump(mode="json")
    return {key: unit[key] for key in TeachUnit.model_fields}


def public_lesson_payload(raw: dict, *, schema_version: str) -> dict:
    if not raw:
        return {}
    if raw.get("schema_version", schema_version) != schema_version:
        raise ValueError("unsupported_teach_schema_version")
    draft = parse_lesson_draft({**raw, "schema_version": schema_version})
    if draft.payload is None:
        return {}
    payload = draft.payload.model_dump(mode="json")
    return {
        "blocks": [{key: block[key] for key in LessonBlock.model_fields} for block in payload["blocks"]],
        "checks": [{key: check[key] for key in LessonCheck.model_fields} for check in payload["checks"]],
        "next_step": payload["next_step"],
    }


def draft_hash(raw: dict | BaseModel) -> str:
    """Canonical JSON SHA-256 shared by publication, review and repair records."""
    return digest(dump(raw))
