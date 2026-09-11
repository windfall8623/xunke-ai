"""Deterministic catalog coverage planning, with no implicit LLM/query expansion."""

from __future__ import annotations

from app.rag.contracts import (
    CoveragePlan,
    CoverageStrategy,
    CoverageTarget,
    DocumentEvidence,
    stable_hash,
)
from app.rag.providers.lexical import tokenize_for_retrieval


def plan_coverage(
    spec,
    scope,
    catalog=None,
    *,
    max_subqueries=3,
    strategy: CoverageStrategy = "catalog-v1",
) -> CoveragePlan:
    if strategy not in {"single-goal-v1", "catalog-v1"}:
        raise ValueError("Unknown coverage planning strategy")
    catalog = catalog or {}
    candidates = []
    topic_terms = set(tokenize_for_retrieval(spec.user_input))
    if strategy == "single-goal-v1":
        candidates = [(spec.user_input, [s.doc_id for s in scope.documents], [])]
    elif spec.objective_titles:
        candidates = [
            (title, [s.doc_id for s in scope.documents], [])
            for title in spec.objective_titles
        ]
    else:
        for source in scope.documents:
            sections = (
                catalog.get(source.doc_id, []) if isinstance(catalog, dict) else catalog
            )
            for section in sections:
                if source.section_ids and section.section_id not in source.section_ids:
                    # The engine passes descendants explicitly when a parent is selected.
                    continue
                candidates.append(
                    (section.title, [source.doc_id], [section.section_id])
                )
    if candidates:
        scored = [
            (
                len(topic_terms & set(tokenize_for_retrieval(title))),
                i,
                (title, docs, sections),
            )
            for i, (title, docs, sections) in enumerate(candidates)
        ]
        if any(score > 0 for score, _, _ in scored):
            candidates = [
                item
                for score, _, item in sorted(scored, key=lambda x: (-x[0], x[1]))
                if score > 0
            ]
        candidates = candidates[: min(spec.question_count, max_subqueries)]
    if not candidates:
        candidates = [(spec.user_input, [s.doc_id for s in scope.documents], [])]
    count = len(candidates)
    targets = [
        CoverageTarget(
            target_id="goal_" + stable_hash([title, docs, sections])[:16],
            title=title,
            doc_ids=docs,
            section_ids=sections,
            question_quota=spec.question_count // count
            + (index < spec.question_count % count),
        )
        for index, (title, docs, sections) in enumerate(candidates)
    ]
    queries = list(
        dict.fromkeys(
            spec.user_input
            if t.title == spec.user_input
            else spec.user_input + " " + t.title
            for t in targets
        )
    )
    return CoveragePlan(targets=targets, subqueries=queries[:max_subqueries])


def bind_coverage(plan: CoveragePlan, evidence) -> CoveragePlan:
    targets = []
    for target in plan.targets:
        matches = []
        for item in evidence:
            if isinstance(item, DocumentEvidence):
                if target.doc_ids and item.doc_id not in target.doc_ids:
                    continue
                if target.section_ids and not set(target.section_ids) & {
                    item.locator.section_id,
                    *item.locator.section_ids,
                }:
                    continue
            # Explicit web supplementation can support an objective; semantic checking
            # still has to show the provided text supports each generated question.
            matches.append(item.evidence_id)
        targets.append(target.model_copy(update={"evidence_ids": matches}))
    return plan.model_copy(update={"targets": targets})


def missing_coverage(plan: CoveragePlan) -> list[CoverageTarget]:
    return [target for target in plan.targets if not target.evidence_ids]
