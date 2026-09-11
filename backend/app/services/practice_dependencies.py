"""Body-free discovery of a practice's immutable generation dependencies."""

from typing import Annotated

from pydantic import Field, ValidationError, model_validator

from app.core.errors import not_found
from app.core.values import load
from app.learning.contracts import ConceptIds, LearningId
from app.rag.contracts import Contract, Hash


Revision = Annotated[int, Field(ge=1)]
# Do not load objectives, question bodies or provider configuration merely to
# discover which sources must be locked. All paths are fixed server constants.
METADATA_SQL = (
    "JSON_OBJECT("
    "'practice_id',JSON_EXTRACT(generation_request_json,'$.practice_id'),"
    "'generation_request_id',JSON_EXTRACT(generation_request_json,'$.generation_request_id'),"
    "'space_id',JSON_EXTRACT(generation_request_json,'$.spec.space_id'),"
    "'scope_revision',JSON_EXTRACT(generation_request_json,'$.spec.scope_revision'),"
    "'concept_ids',JSON_EXTRACT(generation_request_json,'$.spec.concept_ids'),"
    "'scope_fingerprint',JSON_EXTRACT(generation_request_json,'$.scope_fingerprint'),"
    "'concept_scope_revisions',JSON_EXTRACT(generation_request_json,'$.concept_scope_revisions'),"
    "'space_title_scope_revision',JSON_EXTRACT(generation_request_json,'$.space_title_scope_revision')"
    ") AS generation_metadata_json"
)


class PracticeMetadata(Contract):
    practice_id: LearningId
    generation_request_id: LearningId
    space_id: LearningId
    scope_revision: Revision
    concept_ids: ConceptIds
    scope_fingerprint: Hash
    concept_scope_revisions: dict[LearningId, Revision]
    space_title_scope_revision: Revision

    @model_validator(mode="after")
    def complete_identity(self):
        if self.practice_id != self.generation_request_id or set(
            self.concept_ids
        ) != set(self.concept_scope_revisions):
            raise ValueError("The saved practice requires complete frozen provenance")
        return self

    @property
    def revisions(self):
        return {
            self.scope_revision,
            self.space_title_scope_revision,
            *self.concept_scope_revisions.values(),
        }


def frozen_metadata(row, scope):
    """Validate the immutable metadata against its owned activity root."""
    try:
        metadata = PracticeMetadata.model_validate(
            load(row["generation_metadata_json"])
        )
    except (KeyError, ValidationError, ValueError, TypeError) as exc:
        raise not_found() from exc
    if (
        metadata.practice_id != row["practice_id"]
        or metadata.space_id != row["space_id"]
        or metadata.scope_revision != row["scope_revision"]
        or metadata.scope_fingerprint != scope.fingerprint
        or scope.owner_id != row["owner_id"]
        or scope.namespace != "production"
        or not scope.documents
    ):
        raise not_found()
    return metadata
