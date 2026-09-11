"""JSON-only RAG boundary types. Offsets are [start, end) Unicode code points.

These types intentionally do not import HTTP, SQL, LangChain or LlamaIndex.
The application must authorize manifests before they enter ResolvedScope.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Hash = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identity = Annotated[str, Field(min_length=1, max_length=256)]
SourcePolicy = Literal["topic", "strict_docs", "doc_plus_web"]
ExecutionMode = Literal["production", "evaluation"]
CoverageStrategy = Literal["single-goal-v1", "catalog-v1"]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_hash(value: Any) -> str:
    return text_hash(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ActorContext(Contract):
    owner_id: int = Field(gt=0)
    roles: list[str] = Field(default_factory=lambda: ["learner"])

    @model_validator(mode="before")
    @classmethod
    def accept_role(cls, value: Any) -> Any:
        if isinstance(value, dict) and "role" in value:
            value = dict(value)
            value.setdefault("roles", [value.pop("role")])
        return value

    @property
    def role(self) -> str:
        return "evaluator" if "evaluator" in self.roles else "learner"


class RequestedDocument(Contract):
    doc_id: Identity
    section_catalog_revision: str | None = None
    section_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def section_revision_required(self):
        if bool(self.section_ids) != bool(self.section_catalog_revision):
            raise ValueError(
                "Section IDs and section catalog revision are required together"
            )
        return self

    @field_validator("section_ids")
    @classmethod
    def distinct_sections(cls, value):
        return list(dict.fromkeys(value))


class RequestedScope(Contract):
    type: Literal["selected_documents"] = "selected_documents"
    documents: list[RequestedDocument] = Field(min_length=1, max_length=5)

    @field_validator("documents", mode="before")
    @classmethod
    def distinct_documents(cls, value):
        if not isinstance(value, list):
            return value
        result, seen = [], {}
        for item in value:
            data = item.model_dump() if isinstance(item, BaseModel) else item
            identity = data.get("doc_id") if isinstance(data, dict) else None
            if identity in seen and seen[identity] != data:
                raise ValueError("Conflicting selections for the same document")
            if identity not in seen:
                result.append(item)
                seen[identity] = data
        return result


class QuizSpec(Contract):
    user_input: str = Field(min_length=1, max_length=2000)
    question_count: int = Field(default=5, ge=3, le=10)
    difficulty: Literal["easy", "medium", "hard", "mixed"] = "mixed"
    source_policy: SourcePolicy = "topic"
    scope: RequestedScope | None = None
    objective_titles: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="before")
    @classmethod
    def normalize_compatibility(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        doc_id = data.pop("doc_id", None)
        scope = data.get("scope")
        if doc_id is not None:
            if scope is not None:
                raise ValueError("doc_id and scope are mutually exclusive")
            scope = {"type": "selected_documents", "documents": [{"doc_id": doc_id}]}
            data["scope"] = scope
        policy = data.get("source_policy")
        if policy is None:
            policy = "strict_docs" if scope is not None else "topic"
        if policy == "topic" and scope is not None:
            raise ValueError("topic cannot select private documents")
        if policy in ("strict_docs", "doc_plus_web") and scope is None:
            raise ValueError("Document policy requires an explicit document scope")
        data["source_policy"] = policy
        return data

    @field_validator("user_input")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Learning topic must not be blank")
        return value.strip()


class SourceManifest(Contract):
    owner_id: int = Field(gt=0)
    namespace: Identity
    doc_id: Identity
    document_version_id: Identity
    source_sha256: Hash
    parse_artifact_id: Identity
    canonical_text_hash: Hash
    index_build_id: Identity
    attempt_id: Identity
    authorization_revision: int = Field(ge=1)
    index_profile_id: str = "legacy-char-v1"
    index_profile_hash: str = ""
    projection_key: str = ""
    canonical_artifact_key: str = ""
    title: str = ""
    section_ids: list[str] = Field(default_factory=list)
    section_catalog_revision: str | None = None

    @model_validator(mode="after")
    def sections_are_parse_bound(self):
        if (
            self.section_catalog_revision
            and self.section_catalog_revision != self.parse_artifact_id
        ):
            raise ValueError("Stale section catalog revision")
        if any(
            not s.startswith(self.parse_artifact_id + ":") for s in self.section_ids
        ):
            raise ValueError("Section does not belong to the parse artifact")
        return self


class ResolvedScope(Contract):
    owner_id: int = Field(gt=0)
    namespace: Identity
    documents: list[SourceManifest] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def same_owner_and_namespace(self):
        if any(
            d.owner_id != self.owner_id or d.namespace != self.namespace
            for d in self.documents
        ):
            raise ValueError("Mixed owner or namespace scope")
        if len({d.doc_id for d in self.documents}) != len(self.documents):
            raise ValueError("Duplicate document in resolved scope")
        return self

    @property
    def fingerprint(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class BudgetLimits(Contract):
    max_llm_calls: int = Field(default=5, ge=0, le=5)
    max_embedding_calls: int = Field(default=100, ge=0, le=1000)
    max_reranker_calls: int = Field(default=2, ge=0, le=6)
    max_search_calls: int = Field(default=2, ge=0, le=6)
    max_fetch_calls: int = Field(default=10, ge=0, le=30)
    max_input_tokens: int = Field(default=60000, ge=0)
    max_output_tokens: int = Field(default=12000, ge=0)
    max_cost_usd: float | None = Field(default=None, ge=0)
    deadline_seconds: float = Field(default=180, gt=0, le=1800)


class Usage(Contract):
    llm_calls: int = Field(default=0, ge=0)
    embedding_calls: int = Field(default=0, ge=0)
    reranker_calls: int = Field(default=0, ge=0)
    search_calls: int = Field(default=0, ge=0)
    fetch_calls: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    embedding_tokens: int = Field(default=0, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    cost_status: Literal["unreported", "estimated", "reported"] = "unreported"
    token_count_method: str = "provider-reported-or-utf8-upper-bound-v1"
    stage_ms: dict[str, float] = Field(default_factory=dict)


class ExecutionContext(Contract):
    mode: ExecutionMode
    run_id: Identity
    storage_namespace: Identity
    budget: BudgetLimits = Field(default_factory=BudgetLimits)


class SourceInput(Contract):
    owner_id: int = Field(gt=0)
    namespace: Identity
    doc_id: Identity
    document_version_id: Identity
    file_path: str
    file_type: Literal["pdf", "docx", "md", "txt"]
    title: str = ""
    source_sha256: Hash | None = None
    max_bytes: int = Field(default=10 * 1024 * 1024, gt=0, le=10 * 1024 * 1024)
    max_pages: int = Field(default=1000, ge=1, le=1000)


class CanonicalBlock(Contract):
    block_id: Identity
    kind: Literal["paragraph", "heading", "table_row", "page", "code"]
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    section_id: Identity
    heading_path: list[str] = Field(default_factory=list)
    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    table_row: int | None = Field(default=None, ge=1)
    heading_level: int | None = Field(default=None, ge=1, le=9)


class Section(Contract):
    section_id: Identity
    title: str
    heading_path: list[str] = Field(default_factory=list)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    level: int = Field(default=1, ge=0, le=9)


class CanonicalDocument(Contract):
    schema_version: Literal["canonical-document.v1"] = "canonical-document.v1"
    owner_id: int = Field(gt=0)
    namespace: Identity
    doc_id: Identity
    document_version_id: Identity
    title: str
    file_type: Literal["pdf", "docx", "md", "txt"]
    source_sha256: Hash
    parse_artifact_id: Identity
    canonical_text_hash: Hash
    parser_version: str
    normalizer_version: str
    text: str = Field(min_length=1)
    blocks: list[CanonicalBlock] = Field(min_length=1)
    sections: list[Section] = Field(default_factory=list)

    @model_validator(mode="after")
    def verify_text_and_ranges(self):
        if text_hash(self.text) != self.canonical_text_hash:
            raise ValueError("Canonical text checksum does not match")
        for block in self.blocks:
            if not (0 <= block.start_char < block.end_char <= len(self.text)):
                raise ValueError("Block is outside canonical text")
            if not block.block_id.startswith(self.parse_artifact_id + ":"):
                raise ValueError("Block has a different parse identity")
        for section in self.sections:
            if not (0 <= section.start_char < section.end_char <= len(self.text)):
                raise ValueError("Section is outside canonical text")
        return self


class DocumentLocator(Contract):
    source_sha256: Hash
    parse_artifact_id: Identity
    canonical_text_hash: Hash
    parser_version: str
    normalizer_version: str
    block_id: Identity
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    quote_hash: Hash
    section_id: str | None = None
    section_ids: list[str] = Field(default_factory=list)
    block_ids: list[str] = Field(default_factory=list)
    heading_path: list[str] = Field(default_factory=list)
    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    table_row: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def ordered_span(self):
        if self.end_char <= self.start_char:
            raise ValueError("Locator must be a nonempty half-open span")
        return self


class WebLocator(Contract):
    block_id: Identity
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    quote_hash: Hash

    @model_validator(mode="after")
    def ordered_span(self):
        if self.end_char <= self.start_char:
            raise ValueError("Locator must be a nonempty half-open span")
        return self


class EvidenceBase(Contract):
    evidence_id: Identity
    owner_id: int = Field(gt=0)
    namespace: Identity
    title: str
    excerpt: str = Field(min_length=1)
    text_hash: Hash
    score: float | None = None
    retrieval_scores: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def quote_is_exact(self):
        if (
            text_hash(self.excerpt) != self.text_hash
            or self.locator.quote_hash != self.text_hash
        ):
            raise ValueError("Evidence quote checksum does not match")
        if len(self.excerpt) != self.locator.end_char - self.locator.start_char:
            raise ValueError("Evidence quote length does not match code-point span")
        return self


class DocumentEvidence(EvidenceBase):
    source_type: Literal["document"] = "document"
    doc_id: Identity
    document_version_id: Identity
    parse_artifact_id: Identity
    index_build_id: Identity
    attempt_id: Identity
    chunk_id: Identity
    parent_id: str | None = None
    locator: DocumentLocator

    @model_validator(mode="after")
    def parse_identity_matches(self):
        if self.parse_artifact_id != self.locator.parse_artifact_id:
            raise ValueError("Citation parse identity differs from locator")
        return self


class WebEvidence(EvidenceBase):
    source_type: Literal["web"] = "web"
    url: str
    fetched_at: datetime
    snapshot_id: Identity
    snapshot_hash: Hash
    snapshot_artifact_key: str = ""
    locator: WebLocator

    @field_validator("url")
    @classmethod
    def public_url_shape(cls, value):
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Web evidence requires an HTTP(S) URL without credentials")
        return value

    @field_validator("fetched_at")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("Fetch timestamp must include timezone")
        return value


Evidence = Annotated[DocumentEvidence | WebEvidence, Field(discriminator="source_type")]


class IndexProfile(Contract):
    profile_id: str = "legacy-char-v1"
    embedding_model: str = "text-embedding-v4"
    embedding_dimensions: int = Field(default=1024, gt=0, le=65536)
    embedding_space: str = "dashscope-compatible-v1"
    embedding_input_version: str = "plain-canonical-v1"
    chunker: Literal["recursive_character", "structure_token"] = "recursive_character"
    chunk_size: int = Field(default=1000, gt=0)
    chunk_overlap: int = Field(default=150, ge=0)
    child_tokens: int = Field(default=384, gt=0)
    child_overlap_tokens: int = Field(default=64, ge=0)
    parent_tokens: int = Field(default=1200, gt=0)
    budget_tokenizer: str = "utf8-upper-bound-v1"
    tokenizer_version: str = "zh-ascii-v1"

    @model_validator(mode="after")
    def overlap_smaller_than_chunk(self):
        if (
            self.chunk_overlap >= self.chunk_size
            or self.child_overlap_tokens >= self.child_tokens
        ):
            raise ValueError("Overlap must be smaller than chunk size")
        if self.parent_tokens < self.child_tokens:
            raise ValueError("Parent token budget cannot be smaller than child")
        return self

    @property
    def profile_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class LLMRerankerConfig(Contract):
    # API model identifiers may be aliases. Recording them does not assert that
    # a hosted provider has frozen its weights; no credentials enter manifests.
    provider: Literal["deepseek", "anthropic", "openai_compatible"]
    model: Identity
    endpoint_hash: Hash
    prompt_version: Literal["listwise-ranking-v1"] = "listwise-ranking-v1"
    application: Literal["merged-candidates-per-round-v1"] = (
        "merged-candidates-per-round-v1"
    )
    max_input_tokens: int = Field(default=12000, ge=1024, le=30000)
    max_output_tokens: int = Field(default=512, ge=256, le=512)


class RerankerConfig(Contract):
    provider: Literal["none", "bge-v2-m3", "qwen3-reranker-0.6b", "llm"] = "none"
    model_revision: str | None = None
    license: str | None = None
    endpoint: str | None = None
    timeout_seconds: float = Field(default=10, gt=0, le=180)
    allow_rrf_fallback: bool = False
    # Historical remote-reranker JSON and hashes must stay byte-for-byte stable.
    llm: LLMRerankerConfig | None = Field(
        default=None, exclude_if=lambda value: value is None
    )

    @model_validator(mode="before")
    @classmethod
    def default_chat_timeout(cls, value: Any) -> Any:
        if (
            isinstance(value, dict)
            and value.get("provider") == "llm"
            and "timeout_seconds" not in value
        ):
            return {**value, "timeout_seconds": 90}
        return value

    @model_validator(mode="after")
    def model_is_pinned(self):
        if self.provider != "llm" and self.timeout_seconds > 30:
            raise ValueError("Remote reranker timeout cannot exceed 30 seconds")
        if self.provider == "llm":
            if self.llm is None:
                raise ValueError("LLM reranking requires explicit chat configuration")
            if self.endpoint or self.model_revision or self.license:
                raise ValueError("Chat reranking cannot use remote-reranker metadata")
        elif self.llm is not None:
            raise ValueError("Chat metadata requires the LLM reranker provider")
        elif self.provider != "none" and (not self.model_revision or not self.license):
            raise ValueError("Reranker weights revision and license must be explicit")
        return self


class PipelineConfig(Contract):
    pipeline_version: str = "rag-v1"
    index_profile_id: str = "legacy-char-v1"
    index_profile_hash: str | None = None
    retriever: Literal["legacy_dense", "llamaindex_dense", "bm25", "hybrid"] = "hybrid"
    dense_top_k: int = Field(default=20, ge=1, le=20)
    lexical_top_k: int = Field(default=20, ge=1, le=20)
    rrf_k: int = Field(default=60, ge=1)
    candidate_limit: int = Field(default=40, ge=1, le=40)
    final_top_k: int = Field(default=8, ge=1, le=8)
    max_subqueries: int = Field(default=3, ge=1, le=3)
    max_retrieval_rounds: int = Field(default=2, ge=1, le=2)
    max_generation_attempts: int = Field(default=2, ge=1, le=2)
    max_llm_calls: int = Field(default=5, ge=1, le=5)
    context_token_budget: int = Field(default=6000, ge=1, le=6000)
    model_context_window: int = Field(default=32768, ge=2048)
    output_token_reserve: int = Field(default=4096, ge=128, le=12000)
    prompt_version: str = "evidence-quiz-v1"
    generator_model: str = "configured"
    legacy_source_archive_sha256: Hash | None = None
    legacy_source_commit: str | None = None
    parent_expansion: bool = False
    # Absence means the historical catalog planner. Keep it absent on the wire
    # so existing frozen JSON and its pipeline hash survive this schema addition.
    coverage_strategy: CoverageStrategy | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    require_semantic_validation: bool = True
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)

    @model_validator(mode="after")
    def ranking_fits_model_window(self):
        if self.reranker.llm is not None and (
            self.reranker.llm.max_input_tokens + self.reranker.llm.max_output_tokens
            > self.model_context_window
        ):
            raise ValueError(
                "Ranking prompt and output exceed the model context window"
            )
        return self

    @property
    def pipeline_config_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class BuildRequest(Contract):
    index_build_id: Identity
    attempt_id: Identity
    source: SourceInput | None = None
    canonical: CanonicalDocument | None = None
    canonical_artifact_key: str | None = None
    profile: IndexProfile = Field(default_factory=IndexProfile)
    expected_document_revision: int = Field(default=1, ge=1)
    lease_token: str | None = None

    @model_validator(mode="after")
    def one_input(self):
        if (self.source is None) == (self.canonical is None):
            raise ValueError("Exactly one source or canonical document is required")
        return self


class IndexedNode(Contract):
    node_id: Identity
    evidence: DocumentEvidence
    section_ids: list[str] = Field(default_factory=list)
    parent_id: str | None = None
    is_parent: bool = False
    embedding_text: str


class BuildResult(Contract):
    schema_version: Literal["index-build.v1"] = "index-build.v1"
    owner_id: int
    namespace: Identity
    doc_id: Identity
    document_version_id: Identity
    source_sha256: Hash
    parse_artifact_id: Identity
    canonical_text_hash: Hash
    index_build_id: Identity
    attempt_id: Identity
    profile: IndexProfile
    index_profile_hash: Hash
    node_count: int = Field(ge=1)
    embedding_dimensions: int = Field(gt=0)
    projection_key: str
    canonical_artifact_key: str
    nodes: list[IndexedNode]
    checksum: Hash
    expected_document_revision: int = Field(ge=1)
    title: str = ""
    state: Literal["validated_candidate"] = "validated_candidate"

    def to_source_manifest(
        self, authorization_revision: int, section_ids: list[str] | None = None
    ) -> SourceManifest:
        """Only call after SQL publish/CAS accepts this candidate manifest."""
        return SourceManifest(
            owner_id=self.owner_id,
            namespace=self.namespace,
            doc_id=self.doc_id,
            document_version_id=self.document_version_id,
            source_sha256=self.source_sha256,
            parse_artifact_id=self.parse_artifact_id,
            canonical_text_hash=self.canonical_text_hash,
            index_build_id=self.index_build_id,
            attempt_id=self.attempt_id,
            authorization_revision=authorization_revision,
            index_profile_id=self.profile.profile_id,
            index_profile_hash=self.index_profile_hash,
            projection_key=self.projection_key,
            canonical_artifact_key=self.canonical_artifact_key,
            title=self.title,
            section_ids=section_ids or [],
            section_catalog_revision=self.parse_artifact_id if section_ids else None,
        )


class RankScore(Contract):
    id: str
    score: float


class RetrievalResult(Contract):
    evidence: list[Evidence] = Field(default_factory=list)
    candidates: list[Evidence] = Field(default_factory=list)
    rankings: dict[str, list[str]] = Field(default_factory=dict)
    status: Literal["ready", "empty"] = "ready"
    warnings: list[str] = Field(default_factory=list)
    effective_config: dict[str, Any] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)


class CoverageTarget(Contract):
    target_id: Identity
    title: str
    doc_ids: list[str] = Field(default_factory=list)
    section_ids: list[str] = Field(default_factory=list)
    question_quota: int = Field(ge=1, le=10)
    evidence_ids: list[str] = Field(default_factory=list)


class CoveragePlan(Contract):
    targets: list[CoverageTarget] = Field(min_length=1, max_length=10)
    subqueries: list[str] = Field(min_length=1, max_length=3)
    planner_version: str = "deterministic-catalog-v1"


class EvidencePack(Contract):
    trace_id: Identity
    policy: SourcePolicy
    resolved_scope: ResolvedScope
    evidence: list[Evidence] = Field(default_factory=list)
    coverage: CoveragePlan | None = None
    status: Literal["ready", "model_only", "insufficient"]
    warnings: list[str] = Field(default_factory=list)
    usage: Usage = Field(default_factory=Usage)
    provided_evidence_ids: list[str] = Field(default_factory=list)
    context_tokens: int = Field(default=0, ge=0)
    token_count_method: str = "utf8-upper-bound-v1"


class QuestionOption(Contract):
    key: str = Field(min_length=1, max_length=8)
    text: str = Field(min_length=1)


class ArtifactQuestion(Contract):
    id: str = Field(min_length=1, max_length=64)
    type: Literal["single", "multiple", "judge"]
    stem: str = Field(min_length=1)
    options: list[QuestionOption] = Field(min_length=2, max_length=8)
    answer: list[str] = Field(min_length=1, max_length=8)
    explanation: str = Field(min_length=1)
    knowledge_point: str = Field(min_length=1)
    difficulty: Literal["easy", "medium", "hard"]
    citation_refs: list[str] = Field(default_factory=list)
    coverage_target_id: str | None = None
    # Supporting quotes are verbatim source, and are checked independently of IDs.
    support_quotes: list[str] = Field(default_factory=list)


class QuizPayload(Contract):
    title: str = Field(min_length=1)
    summary: str
    questions: list[ArtifactQuestion] = Field(min_length=1, max_length=10)


class ValidationResult(Contract):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    semantic_status: Literal["passed", "failed", "not_evaluated"] = "not_evaluated"
    semantic_details: dict[str, Any] = Field(default_factory=dict)
    provider_usage: Usage | None = None


class GenerationResult(Contract):
    payload: dict[str, Any]
    usage: Usage = Field(default_factory=Usage)


class QuizArtifact(QuizPayload):
    schema_version: Literal["quiz-artifact.v1"] = "quiz-artifact.v1"
    case_type: Literal["quiz"] = "quiz"
    artifact_id: Identity
    run_id: Identity
    owner_id: int
    mode: ExecutionMode
    source_status: Literal["grounded", "model_only", "legacy_unverified"]
    evidence_pack: EvidencePack
    pipeline_version: str
    pipeline_config_hash: Hash
    usage: Usage
    validation: ValidationResult
    effective_config: dict[str, Any] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)


class RetrievalArtifact(Contract):
    case_type: Literal["retrieval"] = "retrieval"
    schema_version: Literal["retrieval-artifact.v1"] = "retrieval-artifact.v1"
    run_id: Identity
    evidence: list[Evidence]
    trace: dict[str, Any] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)


class PolicyArtifact(Contract):
    case_type: Literal["policy"] = "policy"
    schema_version: Literal["policy-artifact.v1"] = "policy-artifact.v1"
    run_id: Identity
    observations: dict[str, Any]
    side_effect_diff: dict[str, Any] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)


EvaluationArtifact = Annotated[
    RetrievalArtifact | QuizArtifact | PolicyArtifact, Field(discriminator="case_type")
]


class PipelineManifest(Contract):
    pipeline_config_hash: Hash
    code_hash: str
    dependency_hash: str
    config: PipelineConfig
    index_profile: IndexProfile
    parser_version: str
    normalizer_version: str
    policy_version: str = "explicit-source-v1"


class RunManifest(Contract):
    run_id: Identity
    mode: ExecutionMode
    pipeline_config_hash: Hash
    resolved_scope: ResolvedScope
    dataset_id: str | None = None
    dataset_version: str | None = None
    judge_version: str | None = None
    cache_state: Literal["cold", "warm", "disabled"] = "disabled"
    hardware: dict[str, str] = Field(default_factory=dict)

    @property
    def execution_fingerprint(self) -> str:
        return stable_hash(self.model_dump(mode="json"))
