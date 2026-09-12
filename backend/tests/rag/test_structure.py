def test_structural_children_and_parents_are_real_source_spans_with_limits(tmp_path):
    from app.rag.budget import count_tokens
    from app.rag.ingestion import load_canonical_document
    from app.rag.structure import chunk_document
    from tests.rag.helpers import request_for

    request = request_for(
        tmp_path, text="# 章节\n" + "协方差需要同时考虑符号和适用条件。" * 100
    )
    canonical = load_canonical_document(request.source)
    profile = request.profile.model_copy(
        update={"chunker": "structure_token", "profile_id": "structure-v1"}
    )
    nodes = chunk_document(canonical, profile, "b1", "a1")
    parents = {n.node_id: n for n in nodes if n.is_parent}
    children = [n for n in nodes if not n.is_parent]
    assert parents and children
    for child in children:
        parent = parents[child.parent_id]
        assert parent.evidence.locator.start_char <= child.evidence.locator.start_char
        assert child.evidence.locator.end_char <= parent.evidence.locator.end_char
        assert count_tokens(child.evidence.excerpt) <= 384
        assert count_tokens(parent.evidence.excerpt) <= 1200
        e = child.evidence
        assert canonical.text[e.locator.start_char : e.locator.end_char] == e.excerpt


def test_legacy_char_chunks_keep_original_embedding_text_and_section_boundary(tmp_path):
    from app.rag.ingestion import load_canonical_document
    from app.rag.structure import chunk_document
    from tests.rag.helpers import request_for

    request = request_for(tmp_path)
    canonical = load_canonical_document(request.source)
    chunks = chunk_document(canonical, request.profile, "b1", "a1")
    assert len(chunks) == 2
    assert all(node.embedding_text == node.evidence.excerpt for node in chunks)
    assert len({node.evidence.locator.section_id for node in chunks}) == 2
