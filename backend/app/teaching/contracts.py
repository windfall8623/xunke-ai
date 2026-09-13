"""Model drafts have local references only; the application owns persistence and grades."""

from typing import Annotated, Literal

from pydantic import Field, TypeAdapter, ValidationError, model_validator

from app.rag.contracts import Contract

TeachSourcePolicy = Literal["topic", "strict_docs"]


class VisualStep(Contract):
    label: str = Field(min_length=1, max_length=80)
    detail: str = Field(default="", max_length=400)


class FlowVisual(Contract):
    kind: Literal["flow"]
    title: str = Field(min_length=1, max_length=120)
    steps: list[VisualStep] = Field(min_length=2, max_length=8)
    fallback_text: str = Field(min_length=1, max_length=2000)


class ComparisonVisual(Contract):
    kind: Literal["comparison"]
    title: str = Field(min_length=1, max_length=120)
    columns: list[str] = Field(min_length=2, max_length=4)
    rows: list[list[str]] = Field(min_length=1, max_length=8)
    fallback_text: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def rows_match_columns(self):
        width = len(self.columns)
        for row in self.rows:
            if len(row) != width or any(len(cell) > 400 for cell in row):
                raise ValueError("comparison_row_width_mismatch")
        return self


class StepsVisual(Contract):
    kind: Literal["steps"]
    title: str = Field(min_length=1, max_length=120)
    steps: list[VisualStep] = Field(min_length=1, max_length=8)
    fallback_text: str = Field(min_length=1, max_length=2000)


LessonVisual = Annotated[
    FlowVisual | ComparisonVisual | StepsVisual,
    Field(discriminator="kind"),
]

_visual_adapter = TypeAdapter(LessonVisual)

VISUAL_UNAVAILABLE_WARNING = "本段图示不可用，已保留文字说明。"


def strip_invalid_visuals(document: dict) -> tuple[dict, list[str]]:
    """可视化是可选增强：无效图形降级为警告，正文与引用校验不受影响。"""
    warnings: list[str] = []
    payload = document.get("payload")
    blocks = payload.get("blocks") if isinstance(payload, dict) else None
    if not isinstance(blocks, list):
        return document, warnings
    for block in blocks:
        if not isinstance(block, dict) or "visual" not in block or block["visual"] is None:
            continue
        try:
            _visual_adapter.validate_python(block["visual"])
        except (ValidationError, ValueError, TypeError):
            block.pop("visual")
            if VISUAL_UNAVAILABLE_WARNING not in warnings:
                warnings.append(VISUAL_UNAVAILABLE_WARNING)
    return document, warnings


class TeachContext(Contract):
    space_id: str | None = None
    course_id: str | None = None
    scope_revision: int | None = None


class TeachSource(Contract):
    source_ref: str = Field(min_length=1, max_length=128)
    kind: Literal["provided_material", "rag_evidence"] = "rag_evidence"
    title: str
    locator: str | None = None
    evidence_id: str | None = None
    document_version_id: str | None = None


class TeachMission(Contract):
    goal: str
    prior_knowledge: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    daily_minutes: int | None = Field(default=None, ge=5, le=120)
    deadline: str | None = None


class TeachConcept(Contract):
    concept_ref: str
    title: str = Field(min_length=1, max_length=200)
    concept_id: str | None = None


class TeachUnit(Contract):
    unit_ref: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    objective: str | None = Field(default=None, max_length=1500)
    concepts: list[TeachConcept] = Field(default_factory=list, max_length=10)
    prerequisite_unit_refs: list[str] | None = None
    estimated_minutes: int | None = Field(default=None, ge=1, le=120)
    source_refs: list[str] = Field(default_factory=list)
    availability: Literal["ready", "material_gap"] = "ready"
    completion_check: str | None = None

    @model_validator(mode="after")
    def available_unit_is_actionable(self):
        if self.availability == "ready" and (
            not self.objective or self.prerequisite_unit_refs is None
            or self.estimated_minutes is None or not self.completion_check
        ):
            raise ValueError("A ready unit needs an objective, prerequisites, duration and completion check")
        return self


class CoursePayload(Contract):
    title: str = Field(min_length=1, max_length=200)
    mission: TeachMission
    units: list[TeachUnit] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def valid_prerequisites(self):
        graph = {u.unit_ref: u.prerequisite_unit_refs or [] for u in self.units}
        if len(graph) != len(self.units):
            raise ValueError("Duplicate unit_ref")
        done, active = set(), set()

        def visit(ref):
            if ref not in graph or ref in active:
                raise ValueError("Unknown or cyclic prerequisite")
            if ref in done:
                return
            active.add(ref)
            for prerequisite in graph[ref]:
                visit(prerequisite)
            active.remove(ref)
            done.add(ref)

        for ref in graph:
            visit(ref)
        return self


class LessonBlock(Contract):
    type: Literal["explanation", "example", "reference", "recap"]
    text: str = Field(min_length=1, max_length=12000)
    source_refs: list[str] = Field(default_factory=list)
    synthetic: bool = False
    # 可选增强：只允许纯文本结构（flow/comparison/steps），不接受 HTML/SVG/URL。
    visual: LessonVisual | None = None


class LessonCheckOption(Contract):
    key: str
    text: str


class LessonCheck(Contract):
    check_ref: str
    question_type: Literal["single", "multiple", "judge", "short_answer", "reflection"] = "reflection"
    prompt: str = Field(min_length=1, max_length=2000)
    options: list[LessonCheckOption] = Field(default_factory=list, max_length=10)


class LessonPayload(Contract):
    unit_ref: str
    title: str
    objective: str
    estimated_minutes: int = Field(ge=1, le=120)
    blocks: list[LessonBlock] = Field(min_length=1, max_length=20)
    checks: list[LessonCheck] = Field(default_factory=list, max_length=5)
    next_step: str


class TeachEnvelope(Contract):
    schema_version: Literal["xunke-teach.v1"] = "xunke-teach.v1"
    source_policy: TeachSourcePolicy
    status: Literal["draft", "needs_input", "needs_sources", "insufficient_evidence"] = "draft"
    context: TeachContext = Field(default_factory=TeachContext)
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    sources: list[TeachSource] = Field(default_factory=list)

    def check_references(self, groups):
        refs = {s.source_ref for s in self.sources}
        if len(refs) != len(self.sources):
            raise ValueError("Duplicate source_ref")
        if self.source_policy == "topic" and (refs or any(group for group, _ in groups)):
            raise ValueError("Topic generation cannot invent citations")
        for group, required in groups:
            if not set(group) <= refs:
                raise ValueError("Unknown source_ref")
            if self.source_policy == "strict_docs" and required and not group:
                raise ValueError("Supported content needs evidence")
        if self.status in ("needs_input", "needs_sources") and self.payload is not None:
            raise ValueError("Unavailable drafts cannot contain content")


class CourseDraft(TeachEnvelope):
    kind: Literal["course_draft"] = "course_draft"
    payload: CoursePayload | None = None

    @model_validator(mode="after")
    def check_sources(self):
        self.check_references([
            (u.source_refs, u.availability == "ready") for u in self.payload.units
        ] if self.payload else [])
        if self.status == "draft" and self.payload is None:
            raise ValueError("A course draft needs content")
        return self


class LessonDraft(TeachEnvelope):
    kind: Literal["lesson_draft"] = "lesson_draft"
    payload: LessonPayload | None = None

    @model_validator(mode="after")
    def check_sources(self):
        self.check_references([
            (b.source_refs, not b.synthetic) for b in self.payload.blocks
        ] if self.payload else [])
        if self.status == "draft" and self.payload is None:
            raise ValueError("A lesson draft needs content")
        return self
