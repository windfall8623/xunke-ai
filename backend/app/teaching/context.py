"""A complete selected catalog for planning, and scoped evidence for one lesson."""

from dataclasses import dataclass, field

from app.core.errors import AppError
from app.core.values import dump
from app.rag.budget import count_tokens
from app.rag.providers.lexical import LexicalIndex
from app.rag.scope import evidence_in_scope
from app.services.source_service import reauthorize_scope
from app.teaching.contracts import TeachSource


@dataclass
class TeachingMaterial:
    catalog: list[dict] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def sources(self):
        return [TeachSource(
            source_ref=ref, kind="rag_evidence", title=item.title,
            locator=" / ".join(item.locator.heading_path) or (
                f"第 {item.locator.page} 页" if item.locator.page else f"段落 {item.locator.paragraph}" if item.locator.paragraph else None),
            evidence_id=item.evidence_id, document_version_id=item.document_version_id,
        ) for ref, item in self.evidence.items()]

    def prompt_data(self):
        return dict(catalog=self.catalog, sources=[s.model_dump(mode="json") for s in self.sources],
                    excerpts=[dict(source_ref=ref, text=e.excerpt) for ref, e in self.evidence.items()],
                    coverage_warnings=self.warnings)


async def outline_material(engine, scope, query=""):
    result = TeachingMaterial()
    if not scope.documents:
        return result
    await reauthorize_scope(scope)
    evidence_by_id = {}
    for source in scope.documents:
        canonical = engine.store.load_canonical(source.canonical_artifact_key)
        built = engine.store.read_build(source)
        nodes = [node for node in built.nodes if not node.is_parent and evidence_in_scope(node.evidence, scope)]
        ranking = LexicalIndex([dict(id=node.node_id, text=node.evidence.excerpt) for node in nodes])
        sections = [s for s in canonical.sections if not source.section_ids or s.section_id in source.section_ids]
        entries = sections or [None]
        for section in entries:
            candidates = [n.evidence for n in nodes if section is None or section.section_id in {n.evidence.locator.section_id, *n.evidence.locator.section_ids}]
            # Choose a goal-relevant paragraph even when a PDF has no headings.
            ranked = ranking.search(query, allowed_ids={e.chunk_id for e in candidates}, top_k=1) if query else []
            evidence = next((e for e in candidates if ranked and e.chunk_id == ranked[0].id), None)
            evidence = evidence or max(candidates, key=lambda e: min(len(e.excerpt), 600), default=None)
            refs = []
            if evidence:
                engine.verify_evidence(evidence, scope)
                ref = evidence_by_id.setdefault(evidence.evidence_id, f"s{len(evidence_by_id) + 1}")
                result.evidence[ref] = evidence
                refs = [ref]
            result.catalog.append(dict(title=section.title if section else source.title,
                                       document_title=source.title, source_refs=refs,
                                       coverage="representative_excerpt" if refs else "material_gap"))
    result.warnings = ["纲要依据所选目录与代表片段规划；每课正文将按目标重新检索，未代表整份资料的逐句核验。"]
    # Never quietly omit later sections to claim complete document coverage.
    if count_tokens(dump(result.prompt_data())) > 6500:
        raise AppError(422, "course_scope_too_large", "所选目录或材料过长，请选择更具体的章节")
    await reauthorize_scope(scope)
    return result


async def lesson_material(engine, scope, unit, config, *, budget):
    if not scope.documents:
        return TeachingMaterial()
    query = "\n".join([unit.title, unit.objective or "", *[c.title for c in unit.concepts]])
    # Bound context, keeping the configured retriever and reranker.
    config = config.model_copy(update={"context_token_budget": 4200, "final_top_k": 4})
    retrieved = await engine.retrieve(query, scope, config, budget=budget)
    if not retrieved.evidence:
        raise AppError(422, "course_material_gap", "当前资料没有足够依据生成本课")
    result = TeachingMaterial(evidence={f"s{i + 1}": item for i, item in enumerate(retrieved.evidence)})
    # Retrieved evidence already represents a bounded, local query, not full coverage.
    if count_tokens(dump(result.prompt_data())) > 6500:
        raise AppError(422, "course_scope_too_large", "本课材料过长，请选择更具体的章节")
    return result
