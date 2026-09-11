from typing import Literal

from pydantic import BaseModel, Field

from app.rag.contracts import (
    CanonicalBlock,
    Contract,
    Hash,
    Identity,
    ResolvedScope,
    Section,
    SourceManifest,
    WebEvidence,
)


class SectionView(BaseModel):
    section_id: str
    title: str


class DocumentView(BaseModel):
    doc_id: str
    file_name: str
    file_type: str
    file_size: int
    status: str
    created_at: str | None = None
    purpose: str = "production"
    active_version_id: str | None = None
    active_build_id: str | None = None
    document_revision: int
    section_catalog_revision: str | None = None
    sections: list[SectionView] = Field(default_factory=list)
    chunk_count: int = 0
    task_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class DocumentList(BaseModel):
    items: list[DocumentView]
    total: int


class ReindexBody(BaseModel):
    index_profile_id: Literal["legacy-char-v1", "structure-v1"] = "legacy-char-v1"


class SourceExcerptLocator(CanonicalBlock):
    quote_hash: str


class SourceExcerptView(BaseModel):
    doc_id: str
    version_id: str
    parse_artifact_id: str
    canonical_text_hash: str
    source_sha256: str
    block_id: str
    excerpt: str
    locator: SourceExcerptLocator
    blocks: list[CanonicalBlock]
    sections: list[Section]


class DocumentDeletionView(BaseModel):
    doc_id: str
    status: Literal["deleted"]
    task_id: str


class PublicWebEvidence(WebEvidence):
    snapshot_artifact_key: str = Field(default="", exclude=True)


class PublicSourceManifest(Contract):
    """Explicit public source identity; storage and worker metadata never enter it."""

    doc_id: Identity
    document_version_id: Identity
    source_sha256: Hash
    parse_artifact_id: Identity
    canonical_text_hash: Hash
    index_build_id: Identity
    authorization_revision: int = Field(ge=1)
    title: str = ""
    section_ids: list[str] = Field(default_factory=list)
    section_catalog_revision: str | None = None

    @classmethod
    def from_source(cls, source: SourceManifest) -> "PublicSourceManifest":
        return cls(
            doc_id=source.doc_id,
            document_version_id=source.document_version_id,
            source_sha256=source.source_sha256,
            parse_artifact_id=source.parse_artifact_id,
            canonical_text_hash=source.canonical_text_hash,
            index_build_id=source.index_build_id,
            authorization_revision=source.authorization_revision,
            title=source.title,
            section_ids=list(source.section_ids),
            section_catalog_revision=source.section_catalog_revision,
        )


class PublicResolvedScope(Contract):
    """Reusable response projection; authorization still uses ResolvedScope."""

    documents: list[PublicSourceManifest] = Field(default_factory=list, max_length=5)

    @classmethod
    def from_scope(cls, scope: ResolvedScope) -> "PublicResolvedScope":
        return cls(
            documents=[
                PublicSourceManifest.from_source(item) for item in scope.documents
            ]
        )
