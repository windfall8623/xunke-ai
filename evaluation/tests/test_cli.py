import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]


def cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "rag_eval.cli", *[str(arg) for arg in args]],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def test_validate_authored_smoke_is_success_but_freeze_is_rejected():
    result = cli("validate", "--dataset", "datasets/smoke/manifest.json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["valid"] is True and data["freezable"] is False
    frozen = cli(
        "validate", "--dataset", "datasets/smoke/manifest.json", "--require-frozen"
    )
    assert frozen.returncode != 0


def test_score_and_compare_smoke_outputs_remain_explicitly_provisional(tmp_path):
    results, run = tmp_path / "results.jsonl", tmp_path / "run.json"
    scored = cli(
        "score",
        "--dataset",
        "datasets/smoke/manifest.json",
        "--artifacts",
        "datasets/smoke/fixture-artifacts.jsonl",
        "--output",
        results,
        "--run-output",
        run,
    )
    assert scored.returncode == 0, scored.stderr
    rows = [
        json.loads(line) for line in results.read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 46
    refusal = next(row for row in rows if row["sample_id"] == "smoke-q-009")
    assert refusal["metrics"]["valid_question_yield"]["status"] == "na"
    assert (
        json.loads(run.read_text(encoding="utf-8"))["manifest"]["gold_reviewed"]
        is False
    )
    report = tmp_path / "comparison.json"
    compared = cli("compare", "--baseline", run, "--candidate", run, "--output", report)
    assert compared.returncode == 0, compared.stderr
    value = json.loads(report.read_text(encoding="utf-8"))
    assert value["provisional"] is True and value["decision"] != "improved"


def test_cli_does_not_silently_select_duplicate_successes(tmp_path):
    line = (
        (ROOT / "datasets/smoke/fixture-artifacts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(line + "\n" + line + "\n", encoding="utf-8")
    result = cli(
        "score", "--dataset", "datasets/smoke/manifest.json", "--artifacts", duplicate
    )
    assert result.returncode != 0
    assert "duplicate" in result.stderr.lower()


def test_cli_calibration_reports_unknowns_without_certifying_the_judge(tmp_path):
    records = tmp_path / "calibration.json"
    records.write_text(
        json.dumps(
            [
                {
                    "question_hash": "fixture-a",
                    "human": None,
                    "judge": True,
                    "split": "judge_calibration",
                }
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "calibration-report.json"
    result = cli("judge-calibration", "--records", records, "--output", output)
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["pending_count"] == 1 and report["calibrated"] is False


def test_cli_judge_runtime_info_is_local_and_requires_the_isolated_extra():
    import importlib.util

    result = cli("judge-info")
    if importlib.util.find_spec("ragas") is None:
        assert result.returncode == 2
        assert "optional_ragas_runtime_missing" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["ragas_version"] == "0.4.3" and report["model_calls"] == 0
        assert len(report["prompt_hash"]) == 64
