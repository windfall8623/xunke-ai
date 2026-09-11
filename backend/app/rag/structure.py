"""Source-preserving character baseline and explicit token-budget structures."""

from __future__ import annotations

from app.rag.budget import count_tokens
from app.rag.contracts import (
    CanonicalDocument,
    DocumentEvidence,
    DocumentLocator,
    IndexedNode,
    IndexProfile,
    stable_hash,
    text_hash,
)


def _groups(document: CanonicalDocument):
    group = []
    for block in document.blocks:
        if group and (block.section_id, block.page) != (
            group[-1].section_id,
            group[-1].page,
        ):
            yield group
            group = []
        group.append(block)
    if group:
        yield group


def _budget_spans(text: str, start: int, end: int, size: int, overlap: int):
    cursor = start
    while cursor < end:
        finish, used = cursor, 0
        while finish < end and used + count_tokens(text[finish]) <= size:
            used += count_tokens(text[finish])
            finish += 1
        if finish == cursor:
            raise ValueError("Token budget cannot hold one Unicode code point")
        yield cursor, finish
        if finish == end:
            break
        next_cursor, used = finish, 0
        while (
            next_cursor > cursor + 1
            and used + count_tokens(text[next_cursor - 1]) <= overlap
        ):
            next_cursor -= 1
            used += count_tokens(text[next_cursor])
        cursor = next_cursor


def chunk_document(
    document: CanonicalDocument, profile: IndexProfile, build_id: str, attempt_id: str
) -> list[IndexedNode]:
    if profile.budget_tokenizer != "utf8-upper-bound-v1":
        raise ValueError("Unregistered budget tokenizer")
    nodes: list[IndexedNode] = []

    def create(start: int, end: int, *, parent_id=None, is_parent=False):
        block = next(
            b for b in document.blocks if b.end_char > start and b.start_char < end
        )
        intersects = [
            b.block_id
            for b in document.blocks
            if b.end_char > start and b.start_char < end
        ]
        sections = [
            s.section_id
            for s in document.sections
            if s.start_char <= start and end <= s.end_char
        ]
        if block.section_id not in sections:
            sections.append(block.section_id)
        identity = [
            document.owner_id,
            document.namespace,
            document.doc_id,
            document.document_version_id,
            document.parse_artifact_id,
            build_id,
            attempt_id,
            block.block_id,
            start,
            end,
            is_parent,
        ]
        node_id = "node_" + stable_hash(identity)
        excerpt = document.text[start:end]
        quote_hash = text_hash(excerpt)
        locator = DocumentLocator(
            source_sha256=document.source_sha256,
            parse_artifact_id=document.parse_artifact_id,
            canonical_text_hash=document.canonical_text_hash,
            parser_version=document.parser_version,
            normalizer_version=document.normalizer_version,
            block_id=block.block_id,
            block_ids=intersects,
            start_char=start,
            end_char=end,
            quote_hash=quote_hash,
            section_id=block.section_id,
            section_ids=sections,
            heading_path=block.heading_path,
            page=block.page,
            paragraph=block.paragraph,
            line_start=block.line_start,
            line_end=block.line_end,
            table_row=block.table_row,
        )
        evidence = DocumentEvidence(
            evidence_id="ev_" + stable_hash(identity),
            owner_id=document.owner_id,
            namespace=document.namespace,
            title=document.title,
            doc_id=document.doc_id,
            document_version_id=document.document_version_id,
            parse_artifact_id=document.parse_artifact_id,
            index_build_id=build_id,
            attempt_id=attempt_id,
            chunk_id=node_id,
            parent_id=parent_id,
            locator=locator,
            excerpt=excerpt,
            text_hash=quote_hash,
        )
        node = IndexedNode(
            node_id=node_id,
            evidence=evidence,
            section_ids=sections,
            parent_id=parent_id,
            is_parent=is_parent,
            embedding_text=excerpt,
        )
        nodes.append(node)
        return node

    for group in _groups(document):
        start, end = group[0].start_char, group[-1].end_char
        if profile.chunker == "recursive_character":
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=profile.chunk_size,
                chunk_overlap=profile.chunk_overlap,
                add_start_index=True,
            )
            for item in splitter.create_documents([document.text[start:end]]):
                a = start + item.metadata["start_index"]
                create(a, a + len(item.page_content))
        else:
            for pa, pb in _budget_spans(
                document.text, start, end, profile.parent_tokens, 0
            ):
                parent = create(pa, pb, is_parent=True)
                for ca, cb in _budget_spans(
                    document.text,
                    pa,
                    pb,
                    profile.child_tokens,
                    profile.child_overlap_tokens,
                ):
                    create(ca, cb, parent_id=parent.node_id)
    return nodes


def expand_parent_context(
    evidence: list[DocumentEvidence], scope, budget: int, nodes: list[IndexedNode]
) -> list[DocumentEvidence]:
    """Expand only to persisted same-attempt parents completely inside the scope."""
    from app.rag.scope import evidence_in_scope

    by_id = {n.node_id: n for n in nodes}
    selected, seen, used = [], set(), 0
    for item in evidence:
        candidate = item
        if item.parent_id:
            parent = by_id.get(item.parent_id)
            if (
                parent
                and parent.is_parent
                and evidence_in_scope(parent.evidence, scope)
                and (parent.evidence.index_build_id, parent.evidence.attempt_id)
                == (item.index_build_id, item.attempt_id)
            ):
                candidate = parent.evidence
        if candidate.evidence_id in seen:
            continue
        if used + count_tokens(candidate.excerpt) > budget:
            candidate = item
        if (
            candidate.evidence_id in seen
            or used + count_tokens(candidate.excerpt) > budget
        ):
            continue
        selected.append(candidate)
        seen.add(candidate.evidence_id)
        used += count_tokens(candidate.excerpt)
    return selected
