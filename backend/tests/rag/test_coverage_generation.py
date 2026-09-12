import pytest


def test_context_uses_complete_blocks_and_only_admits_provided_ids():
    from app.rag.context import assemble_evidence
    from tests.rag.test_artifact_pipeline import context_and_scope

    e, _, _, scope = context_and_scope()
    pack = assemble_evidence([e], scope, "strict_docs", 25, "run1")
    assert (
        not pack.evidence
    )  # quote + ID framing does not fit; do not truncate the quote.
    assert pack.status == "insufficient"
    pack = assemble_evidence([e, e], scope, "strict_docs", 6000, "run1")
    assert len(pack.evidence) == 1
    assert pack.provided_evidence_ids == ["ev_1"]


def test_context_rejects_same_owner_but_wrong_build():
    from app.rag.context import assemble_evidence
    from app.rag.errors import ScopeRevoked
    from tests.rag.test_artifact_pipeline import context_and_scope

    e, _, _, scope = context_and_scope()
    with pytest.raises(ScopeRevoked):
        assemble_evidence(
            [e.model_copy(update={"index_build_id": "other"})],
            scope,
            "strict_docs",
            6000,
            "run1",
        )


def test_coverage_quota_matches_requested_count_and_bounded_subqueries(tmp_path):
    from app.rag.coverage import plan_coverage
    from app.rag.ingestion import load_canonical_document
    from app.rag.scope import normalize_spec
    from tests.rag.helpers import request_for
    from tests.rag.test_artifact_pipeline import context_and_scope

    _, _, _, scope = context_and_scope()
    canonical = load_canonical_document(request_for(tmp_path).source)
    plan = plan_coverage(
        normalize_spec(
            {"user_input": "完整学习", "doc_id": "doc_1", "question_count": 10}
        ),
        scope,
        {"doc_1": canonical.sections},
    )
    assert sum(target.question_quota for target in plan.targets) == 10
    assert len(plan.subqueries) <= 3
    assert len(plan.targets) == 2


def test_validation_rejects_incorrect_answer_sets_false_unknown_and_duplicates():
    from app.rag.context import assemble_evidence
    from app.rag.coverage import bind_coverage, plan_coverage
    from app.rag.validation import validate_quiz_artifact
    from tests.rag.test_artifact_pipeline import (
        context_and_scope,
        quiz_for,
        strict_spec,
    )

    e, _, _, scope = context_and_scope()
    spec = strict_spec()
    plan = bind_coverage(plan_coverage(spec, scope), [e])
    pack = assemble_evidence([e], scope, "strict_docs", 6000, "run1", coverage=plan)
    quiz = quiz_for(spec, pack, plan)
    quiz["questions"][0]["answer"] = ["Z"]
    quiz["questions"][1]["stem"] = quiz["questions"][2]["stem"]
    quiz["questions"][2]["support_quotes"] = ["原文没有提及"]
    validation = validate_quiz_artifact(quiz, spec, pack)
    assert not validation.passed
    assert any("answer" in error for error in validation.errors)
    assert any("duplicate" in error for error in validation.errors)
    assert any("support" in error for error in validation.errors)
