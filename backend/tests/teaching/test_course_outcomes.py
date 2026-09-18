"""Course results use settled, explicitly mapped and versioned evidence."""

import pytest


def test_recognition_needs_all_confirmed_independent_items_and_current_versions():
    from app.models.course_outcome import CourseCriterion
    from app.services.course_outcome_service import project_criterion_outcome

    criterion = CourseCriterion(
        course_criterion_id="criterion_1", course_criterion_ref="cc1",
        criteria_revision=1, description="识别事务边界", evidence_type="recognition",
        expectation="正确判断事务提交", lesson_ids=["lesson_1"], origin="generated_v2",
    )
    reference = dict(origin_kind="quiz", origin_id="quiz_1", occurred_at="2026-09-13T00:00:00Z")
    fact = dict(
        definition_hash="definition", lesson_versions={"lesson_1": 1},
        evidence_type="recognition", status="graded", confirmation="confirmed",
        passed=True, complete=True, independent_eligible=True,
        help_usage="none", help_usage_source="learner_declaration", reference=reference,
    )

    def project(facts):
        return project_criterion_outcome(criterion, "definition", {"lesson_1": 1}, facts)

    assert project([]).status == "unverified"
    assert project([fact]).status == "verified"
    assert project([{**fact, "passed": False}]).status == "needs_practice"
    assert project([{**fact, "complete": False}]).status == "unverified"
    assert project([{**fact, "help_usage": "unknown"}]).status == "unverified"
    assert project([{**fact, "confirmation": "provisional"}]).status == "unverified"
    assert project([{**fact, "lesson_versions": {"lesson_1": 2}}]).status == "stale"
    assert project([{**fact, "definition_hash": "changed"}]).status == "stale"
    # Another target changing the global revision does not invalidate this definition.
    criterion.criteria_revision = 2
    assert project([fact]).status == "verified"
    criterion.evidence_type = "creation"
    assert project([fact]).status == "unverified"


def test_latest_confirmed_error_is_not_hidden_by_previous_success():
    from app.models.course_outcome import CourseCriterion
    from app.services.course_outcome_service import project_criterion_outcome

    criterion = CourseCriterion(
        course_criterion_id="criterion_1", course_criterion_ref="cc1", criteria_revision=1,
        description="识别事务边界", evidence_type="recognition", expectation="能识别",
        lesson_ids=[], origin="generated_v2",
    )
    fact = dict(
        definition_hash="same", lesson_versions={}, evidence_type="recognition",
        status="graded", confirmation="confirmed", passed=True, complete=True,
        independent_eligible=True, help_usage="none", help_usage_source="learner_declaration",
        reference=dict(origin_kind="quiz", origin_id="old", occurred_at="2026-09-12T00:00:00Z"),
    )
    newer = {**fact, "passed": False, "reference": {
        "origin_kind": "quiz", "origin_id": "new", "occurred_at": "2026-09-13T00:00:00Z",
    }}
    outcome = project_criterion_outcome(criterion, "same", {}, [newer, fact])
    assert outcome.status == "needs_practice"
    assert outcome.evidence_refs[0].origin_id == "new"


def test_application_contract_keeps_topic_separate_from_practice_sources():
    from pydantic import ValidationError
    from app.teaching.application import CourseApplicationDraft

    with pytest.raises(ValidationError):
        CourseApplicationDraft.model_validate({
            "source_policy": "topic", "space_id": "pretend-space", "applications": [],
        })
