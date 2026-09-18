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


@pytest.mark.parametrize("role", ["learner", "evaluator", "admin"])
@pytest.mark.parametrize("mode", ["production", "evaluation"])
def test_execution_scope_only_admin_can_evaluate(role, mode):
    from app.rag.contracts import ActorContext, ExecutionContext, ResolvedScope
    from app.rag.errors import ScopeRevoked
    from app.rag.scope import require_execution_scope

    actor = ActorContext(owner_id=7, role=role)
    namespace = "production" if mode == "production" else "evaluation:7"
    scope = ResolvedScope(owner_id=7, namespace=namespace)
    context = ExecutionContext(mode=mode, run_id="run", storage_namespace=namespace)
    if mode == "evaluation" and role != "admin":
        with pytest.raises(ScopeRevoked):
            require_execution_scope(actor, context, scope)
    else:
        require_execution_scope(actor, context, scope)


@pytest.mark.parametrize("change", ["owner", "namespace"])
def test_admin_execution_still_requires_own_isolated_scope(change):
    from app.rag.contracts import ActorContext, ExecutionContext, ResolvedScope
    from app.rag.errors import ScopeRevoked
    from app.rag.scope import require_execution_scope

    actor = ActorContext(owner_id=7, role="admin")
    namespace = "production" if change == "namespace" else "evaluation:7"
    scope = ResolvedScope(owner_id=8 if change == "owner" else 7, namespace=namespace)
    context = ExecutionContext(
        mode="evaluation", run_id="run", storage_namespace=namespace
    )
    with pytest.raises(ScopeRevoked):
        require_execution_scope(actor, context, scope)
