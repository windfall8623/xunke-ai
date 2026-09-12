import copy
from pathlib import Path

from conftest import make_source, make_span

from rag_eval.datasets import load_dataset, validate_dataset


def dataset():
    source = make_source()
    source.update(
        {
            "license": "synthetic_project_fixture",
            "language": "en",
            "document_type": "txt",
        }
    )
    sample = {
        "schema_version": "1",
        "sample_id": "a",
        "case_type": "retrieval",
        "family_ids": ["family-a"],
        "split": "dev",
        "source_refs": [source],
        "tags": ["synthetic"],
        "query": "What do plants need?",
        "expected_outcome": "answerable",
        "gold_evidence_groups": [
            {
                "group_id": "light",
                "alternatives": [{"spans": [make_span(source, 0, 17)]}],
            }
        ],
        "annotation": {
            "provenance": "model_draft",
            "review_records": [],
            "disputed": False,
        },
    }
    manifest = {
        "schema_version": "1",
        "dataset_id": "test",
        "version": 1,
        "revision": 1,
        "state": "draft",
        "annotation_version": "draft-v1",
        "sources": [source],
        "review": {"reviewers": [], "checklist": {}},
    }
    return manifest, [sample]


def test_model_draft_can_validate_for_smoke_but_is_not_freezable():
    manifest, samples = dataset()
    report = validate_dataset(manifest, samples)
    assert report["valid"] is True
    assert report["freezable"] is False
    assert "human_review_incomplete" in [item["code"] for item in report["warnings"]]


def test_model_draft_cannot_masquerade_as_frozen_gold():
    manifest, samples = dataset()
    manifest["state"] = "frozen"
    report = validate_dataset(manifest, samples)
    assert report["valid"] is False
    assert "human_review_incomplete" in [item["code"] for item in report["errors"]]


def test_partial_or_wrong_quote_hash_is_rejected():
    manifest, samples = dataset()
    samples[0]["gold_evidence_groups"][0]["alternatives"][0]["spans"][0][
        "quote_hash"
    ] = "0" * 64
    report = validate_dataset(manifest, samples)
    assert report["valid"] is False
    assert any(item["code"] == "gold_quote_hash_mismatch" for item in report["errors"])


def test_source_revoke_blocks_dataset_execution():
    manifest, samples = dataset()
    manifest["sources"][0]["revoked"] = True
    assert validate_dataset(manifest, samples)["valid"] is False


def test_multidocument_connected_family_cannot_cross_splits():
    manifest, samples = dataset()
    other = copy.deepcopy(samples[0])
    other["sample_id"], other["split"] = "b", "locked_test"
    report = validate_dataset(manifest, samples + [other])
    assert report["valid"] is False
    assert any(item["code"] == "cluster_split_leakage" for item in report["errors"])


def test_identical_text_under_different_document_families_cannot_cross_splits():
    manifest, samples = dataset()
    other_source = {
        **manifest["sources"][0],
        "doc_id": "copied-doc",
        "family_id": "claimed-other-family",
    }
    manifest["sources"].append(other_source)
    sample = {
        **copy.deepcopy(samples[0]),
        "sample_id": "copied-sample",
        "split": "locked_test",
        "family_ids": [other_source["family_id"]],
        "source_refs": [other_source],
        "gold_evidence_groups": [
            {
                "group_id": "light",
                "alternatives": [{"spans": [make_span(other_source, 0, 17)]}],
            }
        ],
    }
    report = validate_dataset(manifest, [*samples, sample])
    assert report["valid"] is False
    assert any(item["code"] == "cluster_split_leakage" for item in report["errors"])
    assert (
        report["source_similarity_audit"]["connected_pairs"][0]["reason"]
        == "identical_normalized_text"
    )


def test_small_edits_do_not_hide_near_duplicate_split_leakage():
    manifest, samples = dataset()
    text = "Plants use light. Water is required. " + " ".join(
        f"Synthetic observation {index}: unchanged measurement." for index in range(40)
    )
    source = make_source(text)
    source["license"] = "synthetic_project_fixture"
    other = make_source(
        text.replace("observation 20:", "observation twenty:"),
        "near-copy",
        "family-copy",
    )
    other["license"] = "synthetic_project_fixture"
    manifest["sources"] = [source, other]
    samples[0]["source_refs"] = [source]
    samples[0]["gold_evidence_groups"] = [
        {"group_id": "light", "alternatives": [{"spans": [make_span(source, 0, 17)]}]}
    ]
    duplicate = {
        **copy.deepcopy(samples[0]),
        "sample_id": "near-copy",
        "family_ids": ["family-copy"],
        "source_refs": [other],
        "split": "locked_test",
        "gold_evidence_groups": [
            {
                "group_id": "light",
                "alternatives": [{"spans": [make_span(other, 0, 17)]}],
            }
        ],
    }
    report = validate_dataset(manifest, [*samples, duplicate])
    assert report["valid"] is False
    assert (
        report["source_similarity_audit"]["connected_pairs"][0]["reason"]
        == "near_duplicate_text"
    )


def test_same_reviewer_cannot_count_as_independent_second_review():
    manifest, samples = dataset()
    samples[0]["annotation"]["review_records"] = [
        {
            "reviewer_id": "alice",
            "decision": "approved",
            "reviewed_at": "2026-09-07T01:00:00Z",
            "independent": True,
        },
        {
            "reviewer_id": "alice",
            "decision": "approved",
            "reviewed_at": "2026-09-08T01:00:00Z",
            "independent": True,
        },
    ]
    manifest["review"] = {
        "reviewers": ["alice"],
        "checklist": {
            "source_rights": True,
            "spans": True,
            "family_split": True,
            "answerability": True,
            "second_review": True,
        },
    }
    report = validate_dataset(manifest, samples)
    assert report["freezable"] is False
    assert report["review"]["independently_double_reviewed_count"] == 0


def test_explicit_single_review_freeze_is_marked_provisional():
    manifest, samples = dataset()
    manifest["state"] = "frozen"
    samples[0]["annotation"]["review_records"] = [
        {
            "reviewer_id": "alice",
            "decision": "approved",
            "reviewed_at": "2026-09-07T01:00:00Z",
            "independent": True,
        },
    ]
    manifest["review"] = {
        "reviewers": ["alice"],
        "checklist": {
            "source_rights": True,
            "spans": True,
            "family_split": True,
            "answerability": True,
            "second_review": True,
        },
    }
    report = validate_dataset(manifest, samples, allow_single_review_freeze=True)
    assert report["valid"] is True and report["freezable"] is True
    assert report["release_gold_status"] == "provisional_single_review"
    assert report["formal_gold_eligible"] is False
    assert any(
        item["code"] == "independent_second_review_incomplete"
        for item in report["warnings"]
    )


def test_single_review_option_never_waives_missing_primary_human():
    manifest, samples = dataset()
    manifest["state"] = "frozen"
    report = validate_dataset(manifest, samples, allow_single_review_freeze=True)
    assert report["valid"] is False and report["freezable"] is False


def test_human_approval_does_not_replace_confirming_requested_quiz_sufficiency():
    manifest, samples = dataset()
    manifest["state"] = "frozen"
    manifest["review"] = {
        "checklist": dict.fromkeys(
            [
                "source_rights",
                "spans",
                "family_split",
                "answerability",
                "second_review",
            ],
            True,
        )
    }
    samples[0].update(
        case_type="quiz",
        user_input="Make three questions",
        question_count=3,
        expected_outcome="generate",
        source_sufficient=False,
    )
    samples[0]["annotation"]["review_records"] = [
        {
            "reviewer_id": "alice",
            "decision": "approved",
            "reviewed_at": "2026-09-07T01:00:00Z",
            "independent": True,
        }
    ]
    report = validate_dataset(manifest, samples, allow_single_review_freeze=True)
    assert report["valid"] is False and report["freezable"] is False
    assert any(
        item["code"] == "requested_count_sufficiency_unreviewed"
        for item in report["errors"]
    )


def test_authored_smoke_has_exact_counts_and_valid_real_spans():
    path = Path(__file__).parents[1] / "datasets/smoke/manifest.json"
    assert path.exists(), "authored synthetic smoke dataset has not been seeded"
    manifest, samples = load_dataset(path)
    report = validate_dataset(manifest, samples)
    assert report["valid"] is True
    assert report["counts"]["retrieval"] == 30
    assert report["counts"]["quiz"] == 10
    assert report["counts"]["source_documents"] == 4
    assert report["counts"]["policy"] >= 4
    assert report["freezable"] is False and manifest["state"] == "draft"


def test_pilot_draft_has_real_inventory_without_claiming_human_review():
    path = Path(__file__).parents[1] / "datasets/pilot/manifest.json"
    assert path.exists(), "draft pilot dataset has not been seeded"
    manifest, samples = load_dataset(path)
    report = validate_dataset(manifest, samples)
    assert report["valid"] is True
    assert report["counts"]["retrieval"] == 150 and report["counts"]["quiz"] == 30
    assert report["counts"]["source_documents"] == 20
    assert report["review"]["human_reviewed_count"] == 0
    assert report["freezable"] is False
