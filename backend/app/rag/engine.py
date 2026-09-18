"""Worker-facing RAG facade. Construction never selects a model or fake fallback."""

from __future__ import annotations

from app.rag.contracts import CoveragePlan, DocumentEvidence, PipelineConfig
from app.rag.errors import GenerationValidationFailed, ScopeRevoked, SourceUnavailable
from app.rag.graph_trace import SummarySink
from app.rag.pipeline import PipelinePorts, generate_quiz_artifact, reauthorize_scope
from app.rag.retrieval import HybridRetriever
from app.rag.scope import evidence_in_scope, normalize_spec, require_execution_scope
from app.rag.structure import expand_parent_context


class RagEngine:
    def __init__(
        self,
        store,
        embedding,
        generator=None,
        reauthorize=None,
        *,
        web_provider=None,
        reranker=None,
        llm_reranker=None,
        legacy_baseline=None,
        qa_generator=None,
    ):
        if reauthorize is None:
            raise ValueError("An explicit source authorization callback is required")
        self.store, self.embedding, self.generator = store, embedding, generator
        self.reauthorize, self.web_provider = reauthorize, web_provider
        self.legacy_baseline = legacy_baseline
        self.qa_generator = qa_generator
        # 不可变 build 的内容寻址复用（键含完整投影身份与校验和）。
        # 授权永不缓存：每次业务边界仍然重新检查。
        self._build_cache: dict[tuple, object] = {}
        self.retriever = HybridRetriever(
            store, embedding, reranker=reranker, llm_reranker=llm_reranker,
            build_cache=self._build_cache,
        )

    def _read_build(self, manifest):
        key = (
            manifest.projection_key,
            manifest.canonical_text_hash,
            manifest.index_profile_hash,
        )
        cached = self._build_cache.get(key)
        if cached is None:
            cached = self.store.read_build(manifest)
            if len(self._build_cache) >= 8:
                self._build_cache.pop(next(iter(self._build_cache)))
            self._build_cache[key] = cached
        return cached

    def configure_legacy_baseline(
        self,
        *,
        source_archive,
        archive_sha256,
        llm,
        source_commit="7302ad2",
        summary_agent=None,
    ):
        """Explicitly install the isolated B0 adapter and return its frozen run config."""
        from app.rag.providers.legacy_baseline import LegacyBaselineAdapter

        self.legacy_baseline = LegacyBaselineAdapter(
            source_archive=source_archive,
            archive_sha256=archive_sha256,
            llm=llm,
            retriever=self.retriever,
            reauthorize=self.reauthorize,
            summary_agent=summary_agent,
            web_provider=self.web_provider,
            source_commit=source_commit,
        )
        return self.legacy_baseline.pipeline_config()

    async def build(self, request, *, budget=None):
        """Return an unpublished candidate; caller performs SQL lease/CAS publication."""
        return await self.store.build(request, self.embedding, budget)

    async def retrieve(self, query, scope, config=None, *, budget=None):
        config = config or PipelineConfig()
        await reauthorize_scope(self.reauthorize, scope)
        result = await self.retriever.retrieve_evidence(
            query, scope, config, budget=budget
        )
        if config.parent_expansion:
            nodes = [
                n
                for manifest in scope.documents
                for n in self._read_build(manifest).nodes
            ]
            result.evidence = expand_parent_context(
                result.evidence, scope, config.context_token_budget, nodes
            )
        for item in result.evidence:
            self.verify_evidence(item, scope)
        await reauthorize_scope(self.reauthorize, scope)
        return result

    def verify_evidence(self, evidence, scope):
        if evidence.owner_id != scope.owner_id or evidence.namespace != scope.namespace:
            raise ScopeRevoked(
                "Source evidence belongs to a different owner or namespace"
            )
        if isinstance(evidence, DocumentEvidence):
            source = next(
                (d for d in scope.documents if d.doc_id == evidence.doc_id), None
            )
            if source is None:
                raise ScopeRevoked("Document is outside the selected scope")
            built = self._read_build(source)
            node = next(
                (n for n in built.nodes if n.node_id == evidence.chunk_id), None
            )
            if node is None or node.evidence.model_dump(
                exclude={"score", "retrieval_scores"}
            ) != evidence.model_dump(exclude={"score", "retrieval_scores"}):
                raise SourceUnavailable(
                    "Evidence differs from its immutable source node"
                )
        else:
            snapshot = self.store.load_web_snapshot(evidence.snapshot_artifact_key)
            if (
                snapshot.get("owner_id"),
                snapshot.get("namespace"),
                snapshot.get("snapshot_id"),
                snapshot.get("snapshot_hash"),
                snapshot.get("url"),
            ) != (
                scope.owner_id,
                scope.namespace,
                evidence.snapshot_id,
                evidence.snapshot_hash,
                evidence.url,
            ):
                raise SourceUnavailable("Web evidence snapshot identity does not match")
            if (
                snapshot["text"][
                    evidence.locator.start_char : evidence.locator.end_char
                ]
                != evidence.excerpt
            ):
                raise SourceUnavailable("Web evidence quote differs from its snapshot")

    async def rerank_candidates(self, query, evidence, scope, config, *, budget=None):
        await reauthorize_scope(self.reauthorize, scope)
        for item in evidence:
            if not evidence_in_scope(item, scope):
                raise ScopeRevoked("Ranking candidate is outside the selected scope")
            self.verify_evidence(item, scope)
        result = await self.retriever.rerank_candidates(
            query, evidence, config, budget=budget
        )
        await reauthorize_scope(self.reauthorize, scope)
        return result

    async def generate(
        self,
        spec,
        actor,
        context,
        scope,
        config=None,
        *,
        coverage_plan: CoveragePlan | None = None,
        record_summary: SummarySink | None = None,
    ):
        spec = normalize_spec(spec)
        require_execution_scope(actor, context, scope)
        await reauthorize_scope(self.reauthorize, scope)
        if self.generator is None:
            raise GenerationValidationFailed("Quiz model provider is not configured")
        catalog = {}
        if coverage_plan is None:
            for source in scope.documents:
                built = self._read_build(source)
                catalog[source.doc_id] = self.store.load_canonical(
                    built.canonical_artifact_key
                ).sections
        ports = PipelinePorts(
            retrieve=self.retrieve,
            generate=self.generator.generate,
            reauthorize=self.reauthorize,
            web_search=self.web_provider.retrieve if self.web_provider else None,
            semantic_validator=getattr(self.generator, "validate_semantics", None),
            verify_evidence=self.verify_evidence,
            catalog=catalog,
            estimate_llm_cost=getattr(self.generator, "estimate_cost", None),
            prompt_token_count=getattr(self.generator, "measure_input_tokens", None),
            rerank_candidates=self.rerank_candidates,
            record_summary=record_summary,
        )
        return await generate_quiz_artifact(
            spec,
            actor,
            context,
            ports,
            resolved_scope=scope,
            config=config,
            coverage_plan=coverage_plan,
        )

    async def answer(
        self, question, history, actor, context, scope, config=None, *, progress=None
    ):
        """Return a validated QA artifact; the caller owns durable publication."""
        from app.qa.pipeline import QaPipelinePorts, generate_answer_artifact

        return await generate_answer_artifact(
            question,
            history,
            actor,
            context,
            scope,
            QaPipelinePorts(
                retrieve=self.retrieve,
                reauthorize=self.reauthorize,
                verify_evidence=self.verify_evidence,
                generator=self.qa_generator,
            ),
            config=config,
            progress=progress,
        )
