"""Private practice contracts and learner answers; no HTTP, SQL or providers."""

from __future__ import annotations

import re
from decimal import Decimal, DecimalException, Inexact, localcontext
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    Field,
    StrictStr,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from app.learning.contracts import (
    AssessmentDraft,
    ConceptIds,
    LearningId,
    ObjectiveRef,
    ObjectiveText,
    Score as Score,
)
from app.practice.identity import canonical_question_version, normalize_cloze_text
from app.rag.contracts import (
    Contract,
    DocumentEvidence,
    EvidencePack,
    ExecutionMode,
    Hash,
    Identity,
    ResolvedScope,
    Usage,
    stable_hash,
)
from app.rag.scope import evidence_in_scope

# Keep Decimal's exact, compact serializer, including exponent notation. This
# annotation only corrects its serialization schema; validation bounds stay intact.
FiniteDecimal = Annotated[
    Decimal,
    Field(allow_inf_nan=False),
    WithJsonSchema(
        {
            "type": "string",
            "pattern": r"^-?[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$",
        },
        mode="serialization",
    ),
]
Weight = Annotated[FiniteDecimal, Field(gt=0, le=1)]
QuestionType = Literal["cloze", "numeric", "short_answer"]
Difficulty = Literal["easy", "medium", "hard"]
RequestedDifficulty = Literal["easy", "medium", "hard", "mixed"]
CnyAmount = Annotated[FiniteDecimal, Field(ge=0)]

_NUMERIC_VALUE = re.compile(
    r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z"
)
_BLANK = re.compile(r"\{\{([^{}]*)\}\}")


def _distinct(values: list) -> list:
    if len(set(values)) != len(values):
        raise ValueError("Duplicate identities or values are not allowed")
    return values


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("Text cannot be blank")
    return value


def _weights_total_one(values: list[Decimal]) -> None:
    # All weights are positive and <= 1. Extra carry digits suffice for an
    # exact total of 1; trapping inexact additions rejects tiny hidden excess
    # without allocating a precision proportional to an untrusted exponent.
    with localcontext() as context:
        context.prec = max(len(value.as_tuple().digits) for value in values) + 2
        context.traps[Inexact] = True
        try:
            total = sum(values, Decimal("0"))
        except DecimalException as exc:
            raise ValueError("Rubric weights must sum to exactly 1") from exc
    if total != 1:
        raise ValueError("Rubric weights must sum to exactly 1")


EvidenceRefs = Annotated[list[Identity], AfterValidator(_distinct)]
NonblankText = Annotated[str, AfterValidator(_nonblank)]
QuestionTypes = Annotated[
    list[QuestionType], Field(min_length=1, max_length=3), AfterValidator(_distinct)
]


class PracticeSpec(Contract):
    space_id: LearningId
    scope_revision: int = Field(ge=1)
    objectives: list[ObjectiveText] = Field(min_length=1, max_length=3)
    concept_ids: ConceptIds
    question_types: QuestionTypes
    question_count: int = Field(ge=3, le=10)
    difficulty: RequestedDifficulty

    @model_validator(mode="after")
    def paired_objectives(self):
        if len(self.objectives) != len(self.concept_ids):
            raise ValueError("Each objective must correspond to exactly one concept")
        if len("；".join(self.objectives)) > 2000:
            raise ValueError("Joined objectives must not exceed 2000 characters")
        return self

    @property
    def objective_refs(self) -> list[ObjectiveRef]:
        """Provider input keeps user intention paired with its fixed concept ID."""
        return [
            ObjectiveRef(concept_id=concept_id, title=title)
            for concept_id, title in zip(self.concept_ids, self.objectives, strict=True)
        ]


class PracticeCallUsage(Contract):
    call_id: str
    task_id: str
    attempt: int = Field(ge=1)
    stage: Literal["llm", "embedding", "reranker", "search", "fetch", "images"]
    status: Literal["reserved", "completed", "unknown"]
    # Omit absent historical provenance to preserve sealed artifact hashes.
    config_source: Literal["user", "system"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    cost_cny: CnyAmount | None = None
    reserved_cost_cny: CnyAmount | None = None
    cost_status: Literal["estimated", "unknown", "not_applicable"] = "unknown"


class PracticeUsage(Usage):
    """The worker fills the complete logical-request ledger across task retries."""

    calls: list[PracticeCallUsage] = Field(default_factory=list)
    ledger_complete: bool = False
    cost_cny: CnyAmount | None = None
    known_cost_cny: CnyAmount = Decimal("0")
    reserved_cost_cny: CnyAmount | None = None
    cost_status_cny: Literal[
        "unreported", "estimated", "unknown", "not_applicable"
    ] = "unreported"


class BlankResponse(Contract):
    blank_id: LearningId
    text: str = Field(max_length=500)


class ClozeAnswer(Contract):
    type: Literal["cloze"] = "cloze"
    blanks: list[BlankResponse] = Field(min_length=1, max_length=5)

    @field_validator("blanks")
    @classmethod
    def unique_blank_ids(cls, values):
        _distinct([item.blank_id for item in values])
        return values


class NumericAnswer(Contract):
    type: Literal["numeric"] = "numeric"
    value: StrictStr = Field(min_length=1, max_length=64)
    unit: str = Field(default="", max_length=32)

    @field_validator("value")
    @classmethod
    def bounded_decimal_string(cls, value: str) -> str:
        if _NUMERIC_VALUE.fullmatch(value) is None:
            raise ValueError("Numeric answers require a decimal string")
        try:
            number = Decimal(value)
        except DecimalException as exc:
            raise ValueError("Numeric answer exponent is out of range") from exc
        if not number.is_finite() or not -100 <= number.adjusted() <= 100:
            raise ValueError(
                "Numeric answers must have an adjusted exponent from -100 to 100"
            )
        return value


class ShortAnswer(Contract):
    type: Literal["short_answer"] = "short_answer"
    text: NonblankText = Field(min_length=1, max_length=2000)


TypedAnswer = Annotated[
    ClozeAnswer | NumericAnswer | ShortAnswer,
    Field(discriminator="type"),
]


class ClozeSlot(Contract):
    blank_id: LearningId
    accepted: list[NonblankText] = Field(min_length=1, max_length=10)
    weight: Weight


class ClozeRubric(Contract):
    version: Literal["cloze-rules-v1"] = "cloze-rules-v1"
    normalization: Literal["nfkc-space-v1", "nfkc-space-casefold-v1"] = "nfkc-space-v1"
    slots: list[ClozeSlot] = Field(min_length=1, max_length=5)
    explanation: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def valid_slots(self):
        _distinct([slot.blank_id for slot in self.slots])
        _weights_total_one([slot.weight for slot in self.slots])
        for slot in self.slots:
            normalized = [
                normalize_cloze_text(item, self.normalization) for item in slot.accepted
            ]
            for item in normalized:
                _nonblank(item)
            _distinct(normalized)
        return self


class NumericRubric(Contract):
    version: Literal["numeric-rules-v1"] = "numeric-rules-v1"
    target: FiniteDecimal
    absolute_tolerance: FiniteDecimal = Field(ge=0)
    relative_tolerance: FiniteDecimal = Field(ge=0, le=1)
    unit: str = Field(max_length=32)
    unit_aliases: list[str] = Field(min_length=1, max_length=10)
    explanation: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def canonical_unit_is_declared(self):
        _distinct(self.unit_aliases)
        if self.unit not in self.unit_aliases:
            raise ValueError("Unit aliases must include the canonical unit")
        return self


class RubricCriterion(Contract):
    criterion_id: LearningId
    reference_point: str = Field(min_length=1, max_length=1000)
    weight: Weight
    evidence_refs: EvidenceRefs = Field(min_length=1, max_length=10)


class ShortAnswerRubric(Contract):
    version: Literal["short-answer-v1"] = "short-answer-v1"
    reference_answer: str = Field(min_length=1, max_length=4000)
    criteria: list[RubricCriterion] = Field(min_length=2, max_length=4)
    explanation: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def valid_criteria(self):
        _distinct([criterion.criterion_id for criterion in self.criteria])
        _weights_total_one([criterion.weight for criterion in self.criteria])
        return self


class QuestionBase(Contract):
    id: LearningId
    stem: str = Field(min_length=1)
    difficulty: Difficulty
    concept_ids: ConceptIds
    citation_refs: EvidenceRefs = Field(min_length=1, max_length=10)
    support_quotes: list[NonblankText] = Field(min_length=1, max_length=10)


class ClozeQuestion(QuestionBase):
    type: Literal["cloze"] = "cloze"
    rubric: ClozeRubric

    @model_validator(mode="after")
    def exact_stem_blanks(self):
        remainder = _BLANK.sub("", self.stem)
        if (
            set(_BLANK.findall(self.stem))
            != {slot.blank_id for slot in self.rubric.slots}
            or "{{" in remainder
            or "}}" in remainder
        ):
            raise ValueError("Stem blank IDs must exactly match rubric slots")
        return self


class NumericQuestion(QuestionBase):
    type: Literal["numeric"] = "numeric"
    rubric: NumericRubric


class ShortAnswerQuestion(QuestionBase):
    type: Literal["short_answer"] = "short_answer"
    rubric: ShortAnswerRubric

    @model_validator(mode="after")
    def criterion_evidence_is_cited(self):
        for criterion in self.rubric.criteria:
            if not set(criterion.evidence_refs) <= set(self.citation_refs):
                raise ValueError("Criterion evidence must belong to question citations")
        return self


PracticeQuestion = Annotated[
    ClozeQuestion | NumericQuestion | ShortAnswerQuestion,
    Field(discriminator="type"),
]


class PracticePayload(Contract):
    title: NonblankText = Field(min_length=1)
    summary: str
    questions: list[PracticeQuestion] = Field(min_length=1, max_length=10)

    @field_validator("questions")
    @classmethod
    def unique_question_ids(cls, questions):
        _distinct([question.id for question in questions])
        return questions


class PracticeArtifact(PracticePayload):
    schema_version: Literal["practice-artifact.v1"] = "practice-artifact.v1"
    case_type: Literal["practice_generation"] = "practice_generation"
    artifact_id: Identity
    run_id: Identity
    owner_id: int = Field(gt=0)
    mode: ExecutionMode
    space_id: LearningId
    scope_revision: int = Field(ge=1)
    scope_fingerprint: Hash
    question_versions: dict[LearningId, Hash]
    rubric_hashes: dict[LearningId, Hash]
    evidence_pack: EvidencePack
    pipeline_config_hash: Hash
    prompt_version: LearningId
    prompt_hash: Hash
    model_fingerprint: Identity
    usage: PracticeUsage

    @model_validator(mode="after")
    def verify_private_identity(self):
        pack = self.evidence_pack
        scope: ResolvedScope = pack.resolved_scope
        if (
            self.owner_id != scope.owner_id
            or self.scope_fingerprint != scope.fingerprint
            or not scope.documents
            or pack.policy != "strict_docs"
            or pack.status != "ready"
            or not pack.evidence
        ):
            raise ValueError(
                "Practice artifact requires its complete fixed document scope"
            )
        if self.mode == "production" and scope.namespace != "production":
            raise ValueError("Production artifacts require production sources")
        if self.mode == "evaluation" and not (
            scope.namespace == "evaluation" or scope.namespace.startswith("evaluation:")
        ):
            raise ValueError(
                "Evaluation artifacts require an isolated source namespace"
            )
        for item in pack.evidence:
            if not isinstance(item, DocumentEvidence) or not evidence_in_scope(
                item, scope
            ):
                raise ValueError(
                    "Practice evidence must belong to the fixed document scope"
                )
        evidence_ids = _distinct([item.evidence_id for item in pack.evidence])
        provided_ids = _distinct(pack.provided_evidence_ids)
        if not set(provided_ids) <= set(evidence_ids):
            raise ValueError("Provided evidence IDs must belong to the evidence pack")
        question_ids = {question.id for question in self.questions}
        if (
            set(self.question_versions) != question_ids
            or set(self.rubric_hashes) != question_ids
        ):
            raise ValueError(
                "Version and rubric maps must exactly cover the question IDs"
            )
        for question in self.questions:
            if not set(question.citation_refs) <= set(provided_ids):
                raise ValueError("Practice questions can only cite provided evidence")
            if self.rubric_hashes[question.id] != stable_hash(
                question.rubric.model_dump(mode="json")
            ):
                raise ValueError("Practice rubric checksum does not match")
            if self.question_versions[question.id] != canonical_question_version(
                question, pack
            ):
                raise ValueError("Practice question version does not match")
        return self


class GradeArtifact(Contract):
    """Server-sealed assessment; the grader also verifies its immutable snapshot."""

    schema_version: Literal["grade-artifact.v1"] = "grade-artifact.v1"
    case_type: Literal["answer_grading"] = "answer_grading"
    artifact_id: Identity
    run_id: Identity
    owner_id: int = Field(gt=0)
    mode: ExecutionMode
    attempt_id: LearningId
    grading_request_id: LearningId
    question_version: Hash
    rubric_version: LearningId
    rubric_hash: Hash
    response_hash: Hash
    scope_fingerprint: Hash
    grader_version: LearningId
    model_fingerprint: Identity
    prompt_version: LearningId
    prompt_hash: Hash
    calibration_profile_hash: Hash | None = None
    assessment: AssessmentDraft
    usage: PracticeUsage

    @model_validator(mode="after")
    def consistent_assessment_identity(self):
        if (
            self.assessment.rubric_version != self.rubric_version
            or self.assessment.rubric_hash != self.rubric_hash
            or self.assessment.grader_version != self.grader_version
        ):
            raise ValueError(
                "Grade artifact and assessment scoring identities must agree"
            )
        if (
            self.assessment.source == "model"
            and self.assessment.confirmation == "confirmed"
            and self.calibration_profile_hash is None
        ):
            raise ValueError(
                "Confirmed model grading requires a calibration profile identity"
            )
        return self
