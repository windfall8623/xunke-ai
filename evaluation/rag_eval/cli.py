"""Validate datasets, score saved artifacts, and compare saved runs without I/O to models."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from .comparison import compare_runs, default_protocol
from .contracts import (
    ADAPTER_OBSERVATIONS,
    LEARNING_CASE_TYPES,
    canonical_hash,
    metric_config,
)
from .datasets import load_dataset, validate_dataset, validate_saved_learning_artifact
from .metrics import score_sample


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_atomic(path, text):
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8", newline="\n")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def comparison_markdown(report):
    lines = [
        "# Evaluation comparison",
        "",
        f"Decision: **{report['decision']}**. Provisional: **{report['provisional']}**.",
        "",
        f"Paired requests: {report['sample_count']}; families: {report['family_count']}; independent clusters: {report['cluster_count']}.",
        "",
        "| Metric | Baseline | Candidate | Difference | Paired 95% interval |",
        "|---|---:|---:|---:|---|",
    ]

    def number(value):
        return "unknown / NA" if value is None else f"{value:.4f}"

    for name, value in report["metrics"].items():
        interval = value["ci95"]
        ci = (
            "unavailable"
            if interval is None
            else f"[{number(interval[0])}, {number(interval[1])}]"
            + (" (degenerate)" if value["degenerate"] else "")
        )
        lines.append(
            f"| {name} | {number(value['baseline']['value'])} | {number(value['candidate']['value'])} | {number(value['delta'])} | {ci} |"
        )
    if report["ineligibility_reasons"]:
        lines += [
            "",
            "Formal comparison is unavailable because:",
            "",
            *[f"- {reason}" for reason in report["ineligibility_reasons"]],
        ]
    lines += ["", *report["limitations"], ""]
    return "\n".join(lines)


def _score(args):
    manifest, samples = load_dataset(args.dataset)
    validation = validate_dataset(manifest, samples)
    if not validation["valid"]:
        raise ValueError(
            "dataset validation failed; run validate for structured issues"
        )
    by_id = {sample["sample_id"]: sample for sample in samples}
    kinds = {sample["case_type"] for sample in samples}
    config = metric_config(read_json(args.config) if args.config else None, kinds)
    learning = bool(kinds & LEARNING_CASE_TYPES)
    if learning and ADAPTER_OBSERVATIONS & config.keys():
        raise ValueError(
            "adapter observations cannot be supplied by an offline run config"
        )
    protocol = config.get("comparison_protocol", default_protocol(kinds))
    if not isinstance(protocol, dict) or not protocol.get("protocol_version"):
        raise ValueError("comparison_protocol must declare its protocol_version")
    if learning:
        protocol = {
            **protocol,
            "grading_accept_threshold": config["grading_accept_threshold"],
        }
    rows, seen = [], set()
    raw_artifacts = Path(args.artifacts).read_text(encoding="utf-8-sig").splitlines()
    for line in raw_artifacts:
        if not line.strip():
            continue
        record = json.loads(line)
        artifact = record.get("artifact", record)
        sid = record.get("sample_id", artifact.get("sample_id"))
        repeat = record.get("repeat_index", 0)
        if sid not in by_id or type(repeat) is not int or repeat < 0:
            raise ValueError(
                "artifact has an unknown sample_id or invalid repeat_index"
            )
        if (sid, repeat) in seen:
            raise ValueError(
                "duplicate result identity; final attempts may not be selected by score"
            )
        seen.add((sid, repeat))
        sample = by_id[sid]
        validate_saved_learning_artifact(artifact)
        metrics = score_sample(sample, artifact, config)
        rows.append(
            {
                "sample_id": sid,
                "repeat_index": repeat,
                "case_type": sample["case_type"],
                "family_ids": sample.get("family_ids", []),
                "split": sample["split"],
                "status": "completed",
                "artifact_status": artifact.get("status"),
                "artifact_hash": canonical_hash(artifact),
                "metrics": metrics,
                "artifact_provenance": artifact.get("provenance", "saved_artifact"),
                "annotation_provenance": sample.get("annotation", {}).get(
                    "provenance", "unknown"
                ),
            }
        )
    rows.sort(key=lambda row: (row["sample_id"], row["repeat_index"]))
    serialized = "".join(
        json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows
    )
    if args.output:
        write_atomic(args.output, serialized)
    else:
        sys.stdout.write(serialized)
    repeat_count = config.get(
        "repeat_count", max((row["repeat_index"] for row in rows), default=0) + 1
    )
    planned_ids = sorted(by_id)
    complete = seen == {
        (sid, repeat) for sid in planned_ids for repeat in range(repeat_count)
    }
    run = {
        "run_id": args.run_id or f"offline-{canonical_hash(rows)[:16]}",
        "status": "completed" if complete else "incomplete",
        "manifest": {
            "dataset_id": manifest["dataset_id"],
            "dataset_version": manifest["version"],
            "dataset_hash": manifest.get(
                "dataset_hash", validation["dataset_content_hash"]
            ),
            "annotation_version": manifest.get("annotation_version"),
            "dataset_state": manifest["state"],
            "gold_reviewed": bool(
                validation["freezable"] and manifest["state"] == "frozen"
            ),
            "release_gold_status": validation["release_gold_status"],
            "formal_gold_eligible": validation["formal_gold_eligible"],
            "sample_clusters": {
                sid: cluster
                for cluster, ids in validation["clusters"].items()
                for sid in ids
            },
            "metric_version": config["metric_version"],
            "judge_config_hash": config.get("judge_config_hash", "no-external-judge"),
            "judge_calibrated": config.get("judge_calibrated", False),
            "protocol_frozen": config.get("protocol_frozen", False),
            "cache_protocol": config.get("cache_protocol", "offline_saved_artifacts"),
            "context_token_budget": config.get("context_token_budget", 6000),
            "split": next(iter({sample["split"] for sample in samples}))
            if len({sample["split"] for sample in samples}) == 1
            else "mixed",
            "repeat_count": repeat_count,
            "planned_sample_ids": planned_ids,
            "pipeline_id": config.get("pipeline_id", "saved-artifacts-unconfigured"),
            "provenance": "offline_deterministic_scoring; fixture data are not real provider benchmark outputs",
        },
        "results": rows,
    }
    if learning:
        run["manifest"].update(
            {
                "metric_config": config,
                "metric_config_hash": canonical_hash(config),
                "grading_accept_threshold": config["grading_accept_threshold"],
                "protocol_version": protocol["protocol_version"],
                "comparison_protocol": protocol,
            }
        )
    if args.run_output:
        write_atomic(args.run_output, json_text(run))
    if args.output:
        print(
            json_text(
                {
                    "scored_results": len(rows),
                    "run_complete": complete,
                    "dataset_state": manifest["state"],
                    "human_reviewed": run["manifest"]["gold_reviewed"],
                    "external_model_calls": 0,
                    "results_path": str(Path(args.output).resolve()),
                }
            ).rstrip()
        )
    return 0


def main(argv=None):
    # Windows terminals may use a legacy codepage; JSON remains UTF-8 at pipes.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="Isolated deterministic RAG evaluation of saved JSON artifacts"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser(
        "validate",
        help="Validate real source spans, checksums, family splits, and human-review status",
    )
    validate.add_argument("--dataset", required=True)
    validate.add_argument("--require-frozen", action="store_true")
    validate.add_argument("--output")
    score = commands.add_parser(
        "score", help="Score saved artifacts; no generation or external judge calls"
    )
    score.add_argument("--dataset", required=True)
    score.add_argument("--artifacts", required=True)
    score.add_argument("--config")
    score.add_argument("--output")
    score.add_argument("--run-output")
    score.add_argument("--run-id")
    compare = commands.add_parser(
        "compare", help="Paired connected-cluster bootstrap over saved results"
    )
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    compare.add_argument("--protocol")
    compare.add_argument("--output")
    compare.add_argument("--format", choices=["json", "markdown"], default="json")
    info = commands.add_parser(
        "judge-info",
        help="Inspect the installed Ragas prompt hash without making model calls",
    )
    info.add_argument("--output")
    calibration = commands.add_parser(
        "judge-calibration",
        help="Audit saved human/judge decisions; never auto-certifies calibration",
    )
    calibration.add_argument(
        "--records",
        required=True,
        help="JSON array with question_hash, human, judge, reviewer_id and split",
    )
    calibration.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.command in {"judge-info", "judge-calibration"}:
            from .judges.ragas_adapter import calibration_report, ragas_runtime_info

            report = (
                ragas_runtime_info()
                if args.command == "judge-info"
                else calibration_report(read_json(args.records))
            )
            rendered = json_text(report)
            if args.output:
                write_atomic(args.output, rendered)
            else:
                sys.stdout.write(rendered)
            return 0
        if args.command == "validate":
            manifest, samples = load_dataset(args.dataset)
            report = validate_dataset(
                manifest, samples, require_frozen=args.require_frozen
            )
            rendered = json_text(report)
            if args.output:
                write_atomic(args.output, rendered)
            else:
                sys.stdout.write(rendered)
            return 0 if report["valid"] else 2
        if args.command == "score":
            return _score(args)
        protocol = read_json(args.protocol) if args.protocol else None
        report = compare_runs(
            read_json(args.baseline), read_json(args.candidate), protocol
        )
        rendered = (
            comparison_markdown(report)
            if args.format == "markdown"
            else json_text(report)
        )
        if args.output:
            write_atomic(args.output, rendered)
        else:
            sys.stdout.write(rendered)
        return 0
    except (ValueError, KeyError, OSError, RuntimeError, ImportError) as exc:
        # Validation messages contain field/path identifiers, not source excerpts.
        print(f"Evaluation command failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
