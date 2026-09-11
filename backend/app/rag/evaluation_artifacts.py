"""Public evaluation union, outside base RAG contracts to avoid a QA import cycle."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.practice.contracts import (
    CnyAmount,
    GradeArtifact,
    PracticeArtifact,
    PracticeUsage,
)
from app.qa.contracts import ChatAnswerArtifact
from app.rag.contracts import (
    Contract,
    Identity,
    PolicyArtifact,
    QuizArtifact,
    RetrievalArtifact,
)


class LearningEvaluationUsage(PracticeUsage):
    """One outer provider ledger; private artifact usage is trace-only."""

    calls: list[dict] = Field(default_factory=list)
    unknown_reserved_cost_cny: CnyAmount | None = None
    unknown_call_count: int = Field(default=0, ge=0)


class LearningEvaluationArtifact(Contract):
    schema_version: Literal["1"] = "1"
    run_id: Identity
    sample_id: Identity
    repeat_index: int = Field(default=0, ge=0)
    status: Literal["completed", "refused", "failed", "cancelled", "timeout"]
    error_code: str | None = None
    usage: LearningEvaluationUsage = Field(default_factory=LearningEvaluationUsage)


class PracticeGenerationEvalArtifact(LearningEvaluationArtifact):
    case_type: Literal["practice_generation"] = "practice_generation"
    practice: PracticeArtifact | None = None

    @model_validator(mode="after")
    def complete_or_empty(self):
        if (self.status == "completed") != (self.practice is not None):
            raise ValueError(
                "Only a completed generation may contain a private practice"
            )
        if self.status == "completed" and self.error_code is not None:
            raise ValueError("Completed generation cannot carry an execution error")
        return self


class AnswerGradingEvalArtifact(LearningEvaluationArtifact):
    case_type: Literal["answer_grading"] = "answer_grading"
    grade: GradeArtifact | None = None
    status: Literal["completed", "failed", "cancelled", "timeout"]

    @model_validator(mode="after")
    def complete_or_empty(self):
        if (self.status == "completed") != (self.grade is not None):
            raise ValueError("Only completed grading may contain a private grade")
        if self.status == "completed" and self.error_code is not None:
            raise ValueError("Completed grading cannot carry an execution error")
        return self


EvaluationArtifact = Annotated[
    RetrievalArtifact
    | QuizArtifact
    | ChatAnswerArtifact
    | PolicyArtifact
    | PracticeGenerationEvalArtifact
    | AnswerGradingEvalArtifact,
    Field(discriminator="case_type"),
]
