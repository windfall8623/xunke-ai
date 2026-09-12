"""The baseline executes actual retrieval and is sensitive to wrong expectations."""

import copy

import pytest


def test_engineering_corpus_is_sixty_distinct_draft_cases_with_real_canonical_spans(
    tmp_path,
):
    from rag_eval.datasets import load_dataset, validate_dataset
    from rag_eval.qa_corpus import CATEGORY_COUNTS, write_corpus

    path = write_corpus(tmp_path / "dataset")
    manifest, samples = load_dataset(path)
    report = validate_dataset(manifest, samples)
    assert report["valid"], report["errors"]
    assert report["counts"]["qa"] == 60
    assert len({sample["question"] for sample in samples}) == 60
    assert manifest["engineering_category_counts"] == CATEGORY_COUNTS
    assert report["review"]["human_reviewed_count"] == 0
    assert report["formal_gold_eligible"] is False
    assert all(
        sample["annotation"]["provenance"] == "model_draft" for sample in samples
    )
    assert all(not sample["annotation"]["human_reviewed"] for sample in samples)


@pytest.mark.asyncio
async def test_runner_uses_current_retrieved_text_and_actual_revocation_checks(
    tmp_path,
):
    from rag_eval.datasets import load_dataset
    from rag_eval.qa_corpus import write_corpus
    from rag_eval.qa_engineering import execute_cases

    path = write_corpus(tmp_path / "dataset")
    manifest, samples = load_dataset(path)
    chosen = [
        next(s for s in samples if s["sample_id"] == sid)
        for sid in ("qa-fact-01", "qa-revocation-02", "qa-service_failure-03")
    ]
    report = await execute_cases(manifest, chosen, path.parent, tmp_path / "run")
    assert report["passed"] is True
    assert report["executed_count"] == 3
    assert report["real_model_calls"] == 0
    assert all(row["executed"] for row in report["results"])
    good, revoked, invalid = report["results"]
    assert (
        good["artifact"]["blocks"][0]["text"]
        in good["artifact"]["evidence"][0]["excerpt"]
    )
    assert good["observations"]["retrieval_calls"] == 1
    assert revoked["artifact"]["error_code"] == "SOURCE_UNAVAILABLE"
    assert revoked["observations"]["authorization_denials"] == 1
    assert revoked["observations"]["retrieval_calls"] == 1
    assert invalid["artifact"]["error_code"] == "GENERATION_VALIDATION_FAILED"
    assert invalid["observations"]["chat_stages"] == ["qa_answer"]
    assert report["real_model_cost_cny"] is None
    assert report["real_model_latency_ms"] is None


@pytest.mark.asyncio
async def test_runner_fails_when_expected_answer_was_changed(tmp_path):
    from rag_eval.datasets import load_dataset
    from rag_eval.qa_corpus import write_corpus
    from rag_eval.qa_engineering import execute_cases

    path = write_corpus(tmp_path / "dataset")
    manifest, samples = load_dataset(path)
    wrong = copy.deepcopy(samples[0])
    wrong["expected_answer_status"] = "insufficient_evidence"
    report = await execute_cases(manifest, [wrong], path.parent, tmp_path / "run")
    assert report["passed"] is False
    assert report["results"][0]["artifact"]["answer_status"] == "answered"
    assert report["results"][0]["assertions"]["expected_answer_status"] is False
