"""No request shape can silently expand a private document scope."""

import pytest


@pytest.mark.parametrize(
    "payload,policy,ids",
    [
        ({"user_input": "topic"}, "topic", []),
        ({"user_input": "topic", "source_policy": "topic"}, "topic", []),
        ({"user_input": "topic", "doc_id": "d1"}, "strict_docs", ["d1"]),
        (
            {"user_input": "topic", "doc_id": "d1", "source_policy": "strict_docs"},
            "strict_docs",
            ["d1"],
        ),
        (
            {"user_input": "topic", "doc_id": "d1", "source_policy": "doc_plus_web"},
            "doc_plus_web",
            ["d1"],
        ),
        (
            {
                "user_input": "topic",
                "scope": {
                    "type": "selected_documents",
                    "documents": [{"doc_id": "d1"}, {"doc_id": "d1"}],
                },
            },
            "strict_docs",
            ["d1"],
        ),
    ],
)
def test_policy_matrix(payload, policy, ids):
    from app.rag.scope import normalize_spec

    spec = normalize_spec(payload)
    assert spec.source_policy == policy
    assert ([doc.doc_id for doc in spec.scope.documents] if spec.scope else []) == ids


@pytest.mark.parametrize(
    "payload",
    [
        {"source_policy": "strict_docs"},
        {"source_policy": "doc_plus_web"},
        {"source_policy": "topic", "doc_id": "d1"},
        {
            "doc_id": "d1",
            "scope": {"type": "selected_documents", "documents": [{"doc_id": "d1"}]},
        },
        {"scope": {"type": "selected_documents", "documents": []}},
        {
            "scope": {
                "type": "selected_documents",
                "documents": [{"doc_id": str(i)} for i in range(6)],
            }
        },
        {
            "scope": {
                "type": "selected_documents",
                "documents": [{"doc_id": "d1", "section_ids": ["sec1"]}],
            }
        },
    ],
)
def test_invalid_or_ambiguous_scope_is_rejected(payload):
    from app.rag.errors import InvalidScope
    from app.rag.scope import normalize_spec

    with pytest.raises(InvalidScope):
        normalize_spec({"user_input": "topic", **payload})
