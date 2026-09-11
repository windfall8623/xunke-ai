from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


class DatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    dataset_id: str | None = None
    manifest: dict
    samples: list[dict] = Field(min_length=1, max_length=2000)


class DatasetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    manifest: dict | None = None
    samples: list[dict] | None = Field(default=None, max_length=2000)


class FreezeBody(BaseModel):
    expected_revision: int = Field(ge=1)
    checklist: dict[str, bool] | None = None


class DatasetReview(BaseModel):
    expected_revision: int = Field(ge=1)
    verdict: Literal["approved", "needs_changes"]
    comment: str = Field(default="", max_length=2000)


class DatasetView(BaseModel):
    dataset_id: str
    version: int
    name: str
    status: str
    revision: int
    manifest: dict
    samples: list[dict] = Field(default_factory=list)
    sample_count: int = 0
    split_counts: dict[str, int] = Field(default_factory=dict)
    checksum: str | None = None
    validation: dict | None = None


class DatasetList(BaseModel):
    items: list[DatasetView]
    total: int


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str
    dataset_version: int = Field(ge=1)
    pipeline_id: str
    repeat_count: int = Field(default=2, ge=1, le=2)
    max_cost_cny: float = Field(gt=0, le=1000)
    judge_profile_id: Literal["deterministic-v1", "ragas-faithfulness-v1"] = (
        "deterministic-v1"
    )


class RunEstimateQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str
    dataset_version: int = Field(ge=1)
    pipeline_id: str
    repeat_count: int = Field(default=1, ge=1, le=2)
    judge_profile_id: Literal["deterministic-v1", "ragas-faithfulness-v1"] = (
        "deterministic-v1"
    )


class CostPreviewComponent(BaseModel):
    stage: Literal["retrieval", "generation", "grading", "scoring", "indexing"]
    status: Literal["estimated", "unknown", "not_applicable"]
    first_attempt_cny: float | None = None
    retry_scenario_cny: float | None = None
    first_attempt_calls: int = 0
    retry_scenario_calls: int = 0
    first_attempt_input_tokens: int = 0
    first_attempt_output_tokens: int = 0
    retry_scenario_input_tokens: int = 0
    retry_scenario_output_tokens: int = 0
    prices: dict[str, float | None] = Field(default_factory=dict)
    missing_prices: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    reason: str | None = None


class RunCostPreview(BaseModel):
    status: Literal["estimated", "unknown", "not_applicable"]
    method: Literal["configured_price_scenarios_v1"]
    currency: Literal["CNY"] = "CNY"
    not_a_bill: Literal[True] = True
    pricing_version: str
    sample_count: int
    repeat_count: int
    planned_executions: int
    first_attempt_cny: float | None = None
    retry_scenario_cny: float | None = None
    components: list[CostPreviewComponent]
    assumptions: list[str]


class JudgeProfile(BaseModel):
    judge_profile_id: str
    name: str
    description: str
    calibrated: bool = False


class JudgeProfileList(BaseModel):
    items: list[JudgeProfile]
    total: int


class ProgressView(BaseModel):
    total: int = 0
    completed: int = 0
    failed: int = 0
    pending: int = 0
    scoring: int = 0
    prediction_failed: int = 0


class RunView(BaseModel):
    run_id: str
    dataset_id: str
    dataset_version: int
    pipeline_id: str
    status: str
    stop_reason: str | None = None
    progress: ProgressView
    comparison_eligible: bool = False
    ineligibility_reasons: list[str] = Field(default_factory=list)
    manifest: dict
    max_cost_cny: float
    spent_cny: float = 0
    reserved_cny: float = 0
    created_at: str


class RunList(BaseModel):
    items: list[RunView]
    total: int


class MetricValue(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["ok", "na", "error"]
    value: float | None = None
    numerator: float | None = None
    denominator: float = 0
    unit: str = "ratio"
    metric_version: str = "evidence-v1"
    reason: str | None = None
    unknown_count: int = 0
    applicable_count: int = 0
    error_count: int = 0


class ResultView(BaseModel):
    result_id: str
    sample_id: str
    repeat_index: int
    case_type: str
    status: str
    sample: dict
    artifact: dict | None = None
    metrics: dict[str, MetricValue] | None = None
    review: dict | None = None
    review_revision: int = 0
    error_code: str | None = None


class ResultList(BaseModel):
    items: list[ResultView]
    total: int


class SemanticDecisions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer_correctness: StrictBool | None = None
    source_support: StrictBool | None = None
    solvability: StrictBool | None = None
    explanation_correctness: StrictBool | None = None
    scope_compliance: StrictBool | None = None
    citation_support: StrictBool | None = None
    citation_completeness: StrictBool | None = None
    stem_premise_support: StrictBool | None = None
    distractor_quality: StrictBool | None = None


class QuestionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(min_length=1, max_length=128)
    decisions: SemanticDecisions = Field(default_factory=SemanticDecisions)
    comment: str = Field(default="", max_length=2000)


class ResultReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    verdict: Literal["pass", "fail", "uncertain"]
    comment: str = Field(default="", max_length=2000)
    question_reviews: list[QuestionReview] = Field(default_factory=list, max_length=10)
