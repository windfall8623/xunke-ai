"""Bounded policy cases against disposable synthetic identities only.

This harness exercises domain guards without exposing SQL, Chroma, file deletion,
or production write ports. Its artifact explicitly says in_memory_scope_guards;
application integration tests separately verify SQL lease and cleanup behavior.
"""

from __future__ import annotations

from app.rag.contracts import ActorContext, PolicyArtifact, ResolvedScope, stable_hash
from app.rag.errors import InvalidScope, ScopeRevoked
from app.rag.scope import require_scope

SUPPORTED_ACTIONS = {
    "cross_owner_read",
    "source_delete",
    "source_revoke",
    "expired_authorization",
    "stale_publish",
    "production_side_effect",
}


def validate_policy_harness(sample: dict, scope):
    harness = sample.get("harness", {})
    actors, resources, steps = (
        harness.get("actors", []),
        harness.get("resources", []),
        harness.get("steps", []),
    )
    if (
        harness.get("synthetic_only") is not True
        or not 1 <= len(actors) <= 4
        or not 1 <= len(resources) <= 5
        or not 1 <= len(steps) <= 12
    ):
        raise ScopeRevoked(
            "Policy cases require bounded synthetic actors and isolated copies"
        )
    if any(item.get("synthetic") is not True for item in [*actors, *resources]):
        raise ScopeRevoked(
            "Policy cases cannot operate on real identities or resources"
        )
    if len({item.get("actor_id") for item in actors}) != len(actors) or any(
        not item.get("actor_id") for item in actors
    ):
        raise InvalidScope("Policy actor identities must be distinct")
    allowed_docs = {source.doc_id for source in scope.documents}
    resource_ids = set()
    for resource in resources:
        namespace = resource.get("namespace", "")
        if namespace != "evaluation" and not namespace.startswith("evaluation:"):
            raise ScopeRevoked("Policy targets must be isolated evaluation copies")
        if resource.get("source_doc_id") not in allowed_docs or not resource.get(
            "resource_id"
        ):
            raise ScopeRevoked(
                "Policy copy is not backed by an authorized selected source"
            )
        if resource["resource_id"] in resource_ids:
            raise InvalidScope("Policy resource identities must be distinct")
        resource_ids.add(resource["resource_id"])
    for step in steps:
        if (
            step.get("action") not in SUPPORTED_ACTIONS
            or step.get("target") not in resource_ids
        ):
            raise InvalidScope("Unknown or unbounded policy operation")
    return harness


def run_policy_case(sample, actor, context, scope) -> PolicyArtifact:
    harness = validate_policy_harness(sample, scope)
    require_scope(actor, scope, namespace=context.storage_namespace)
    synthetic_namespace = "evaluation:policy:" + stable_hash(context.run_id)[:12]
    actor_map = {
        item["actor_id"]: ActorContext(owner_id=index + 1000000000, roles=["evaluator"])
        for index, item in enumerate(harness["actors"])
    }
    synthetic_owner = next(iter(actor_map.values()))
    other_actor = next(
        (a for a in actor_map.values() if a.owner_id != synthetic_owner.owner_id),
        ActorContext(owner_id=synthetic_owner.owner_id + 1),
    )
    copies = {}
    for resource in harness["resources"]:
        source = next(
            s for s in scope.documents if s.doc_id == resource["source_doc_id"]
        )
        copy_id = (
            "policy_copy_" + stable_hash([context.run_id, resource["resource_id"]])[:24]
        )
        cloned = source.model_copy(
            update={
                "owner_id": synthetic_owner.owner_id,
                "namespace": synthetic_namespace,
                "doc_id": copy_id,
                "authorization_revision": 1,
            }
        )
        copies[resource["resource_id"]] = {
            "scope": ResolvedScope(
                owner_id=synthetic_owner.owner_id,
                namespace=synthetic_namespace,
                documents=[cloned],
            ),
            "authorization_revision": 1,
            "deleted": False,
            "document_revision": 1,
            "lease_token": "synthetic-lease-1",
        }
    before = {
        key: {name: value for name, value in state.items() if name != "scope"}
        for key, state in copies.items()
    }
    observations = []
    unauthorized = stale = production = 0

    def read_resource(state, requester, pinned_revision=1):
        require_scope(requester, state["scope"], namespace=synthetic_namespace)
        if state["deleted"] or pinned_revision != state["authorization_revision"]:
            raise ScopeRevoked("Synthetic source authorization is invalid")
        return state["scope"]

    for step in harness["steps"]:
        state = copies[step["target"]]
        action = step["action"]
        try:
            if action == "cross_owner_read":
                read_resource(state, other_actor)
                unauthorized += 1
            elif action in ("source_delete", "source_revoke", "expired_authorization"):
                state["authorization_revision"] += 1
                if action == "source_delete":
                    state["deleted"] = True
                    state["document_revision"] += 1
                read_resource(state, synthetic_owner, pinned_revision=1)
                unauthorized += 1
            elif action == "stale_publish":
                expected_revision, prior_lease = (
                    state["document_revision"],
                    state["lease_token"],
                )
                state["document_revision"] += 1
                state["lease_token"] = "synthetic-lease-2"
                if (
                    expected_revision != state["document_revision"]
                    or prior_lease != state["lease_token"]
                ):
                    raise ScopeRevoked("Stale synthetic publication fence")
                stale += 1
            elif action == "production_side_effect":
                require_scope(synthetic_owner, state["scope"], namespace="production")
                production += 1
            observations.append(
                {"action": action, "actual_status": "allowed", "error_code": None}
            )
        except ScopeRevoked as exc:
            observations.append(
                {
                    "action": action,
                    "actual_status": "denied",
                    "error_code": "forbidden",
                    "domain_error_code": exc.code,
                }
            )
    after = {
        key: {name: value for name, value in state.items() if name != "scope"}
        for key, state in copies.items()
    }
    denied = all(item["actual_status"] == "denied" for item in observations)
    return PolicyArtifact(
        run_id=context.run_id,
        observations={
            "actual_status": "denied" if denied else "allowed",
            "error_code": "forbidden" if denied else None,
            "unauthorized_source_count": unauthorized,
            "production_side_effect_count": production,
            "stale_publish_count": stale,
            "executed_step_count": len(observations),
            "steps": observations,
            "harness_kind": "in_memory_scope_guards",
            "sql_lifecycle_coverage": False,
        },
        side_effect_diff={
            "production": {},
            "synthetic_before": before,
            "synthetic_after": after,
        },
    )
