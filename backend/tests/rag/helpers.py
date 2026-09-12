"""Explicit deterministic test provider. Never imported by application code."""

from app.rag.contracts import BuildRequest, IndexProfile, ResolvedScope, SourceInput


class FixtureEmbedding:
    model = "fixture-vector-v1"
    dimensions = 3

    def __init__(self):
        self.calls = []

    async def embed_documents(self, texts, *, budget=None):
        self.calls.append(list(texts))
        if budget:
            budget.reserve("embedding")
        return [[float(t.count("光")), float(t.count("协方差")), 1.0] for t in texts]

    async def embed_query(self, text, *, budget=None):
        return (await self.embed_documents([text], budget=budget))[0]


def request_for(
    tmp_path,
    *,
    doc_id="d1",
    owner_id=7,
    namespace="production",
    build="b1",
    attempt="a1",
    text="# 光合作用\n光合作用需要光。\n# 协方差\n协方差表示共同变化。",
    profile=None,
):
    path = tmp_path / f"{owner_id}-{doc_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return BuildRequest(
        index_build_id=build,
        attempt_id=attempt,
        source=SourceInput(
            owner_id=owner_id,
            namespace=namespace,
            doc_id=doc_id,
            document_version_id="v1",
            title=doc_id,
            file_path=str(path),
            file_type="md",
        ),
        profile=profile
        or IndexProfile(embedding_model="fixture-vector-v1", embedding_dimensions=3),
    )


def scope_for(build, section_ids=None):
    return ResolvedScope(
        owner_id=build.owner_id,
        namespace=build.namespace,
        documents=[
            build.to_source_manifest(authorization_revision=1, section_ids=section_ids)
        ],
    )
