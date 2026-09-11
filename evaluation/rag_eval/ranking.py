"""Canonical-unit projection and tie-aware graded ranking metrics."""

from __future__ import annotations

import math

from .contracts import metric, not_applicable, uncertain
from .evidence import (
    authoritative_texts,
    coverage,
    is_covered,
    provided_ranges,
    span_ranges,
)


def expected_reciprocal_rank(ties: list[list[int]], k: int) -> float:
    preceding = 0
    for grades in ties:
        n = len(grades)
        r = sum(grade >= 2 for grade in grades)
        if r:
            denominator = math.comb(n, r)
            return sum(
                math.comb(n - t, r - 1) / denominator / (preceding + t)
                for t in range(1, min(n - r + 1, k - preceding) + 1)
            )
        preceding += n
        if preceding >= k:
            break
    return 0.0


def tied_dcg(ties: list[list[int]], k: int) -> float:
    position = 1
    total = 0.0
    for grades in ties:
        average_gain = sum(2**grade - 1 for grade in grades) / len(grades)
        total += average_gain * sum(
            1 / math.log2(i + 1)
            for i in range(position, min(k + 1, position + len(grades)))
        )
        position += len(grades)
        if position > k:
            break
    return total


def ranking_metrics(sample: dict, candidates: list[dict], config: dict) -> dict:
    version = config["metric_version"]
    ks = config.get("ranking_ks", [5, 10, 20])
    labels = sample.get("ranking_labels", [])
    output = {}
    if not labels:
        return {
            f"{name}@{k}": not_applicable("no_ranking_gold", version=version)
            for name in ("mrr", "ndcg")
            for k in ks
        }
    invalid = [
        label
        for label in labels
        if type(label.get("grade")) is not int or label["grade"] not in range(4)
    ]
    # Complete-pool declarations cannot silently discard retrieved unjudged text.
    # Whitespace between canonical units does not create an extra ranking unit.
    if sample.get("ranking_pool_complete"):
        labelled = span_ranges(
            span for label in labels for span in label.get("spans", [])
        )
        texts = authoritative_texts(sample, {})
        for identity, ranges in provided_ranges(candidates, sample).items():
            for start, end in ranges:
                cursor = start
                gaps = []
                for a, b in labelled.get(identity, []):
                    if b <= cursor or a >= end:
                        continue
                    if a > cursor:
                        gaps.append((cursor, min(a, end)))
                    cursor = max(cursor, b)
                if cursor < end:
                    gaps.append((cursor, end))
                if any(
                    texts.get(identity) is None or texts[identity][a:b].strip()
                    for a, b in gaps
                ):
                    invalid.append({"grade": None})
    groups = [
        {
            "group_id": unit.get("unit_id", i),
            "alternatives": [{"spans": unit.get("spans", [])}],
        }
        for i, unit in enumerate(labels)
    ]
    _, mapping_unknown = coverage(groups, candidates, sample)
    if invalid or mapping_unknown:
        reason = "unjudged_ranking_units" if invalid else "mapping_failed"
        return {
            f"{name}@{k}": uncertain(0, 1, 1, reason, version=version)
            for name in ("mrr", "ndcg")
            for k in ks
        }
    # Candidate rank ties are accumulated together; one large candidate completing
    # multiple frozen units creates a unit tie, never an arbitrary source ordering.
    ranked: dict[float, list[dict]] = {}
    for index, item in enumerate(candidates):
        rank = item.get("rank", index + 1)
        if type(rank) not in (int, float) or not math.isfinite(rank) or rank < 0:
            raise ValueError("candidate rank must be a finite nonnegative number")
        ranked.setdefault(rank, []).append(item)
    accumulated, completed, ties = [], set(), []
    projection = []
    for rank, items in sorted(ranked.items()):
        accumulated.extend(items)
        ranges = provided_ranges(accumulated, sample)
        newly = [
            index
            for index, label in enumerate(labels)
            if index not in completed
            and label.get("spans")
            and all(is_covered(span, ranges) for span in label["spans"])
        ]
        if newly:
            ties.append([labels[index]["grade"] for index in newly])
            projection.append(
                {
                    "candidate_rank": rank,
                    "unit_ids": [
                        labels[index].get("unit_id", str(index)) for index in newly
                    ],
                }
            )
            completed.update(newly)
    full_grades = [unit["grade"] for unit in labels]
    details = {
        "cutoff_unit": "canonical_source_units",
        "projection": projection,
        "tie_protocol": "uniform_random_permutation_expectation",
        "relevance_threshold": 2,
        "exploratory": not bool(sample.get("ranking_pool_complete")),
        "gold_unit_count": len(labels),
    }
    for k in ks:
        if type(k) is not int or k < 1:
            raise ValueError("ranking cutoffs must be positive integers")
        if any(grade >= 2 for grade in full_grades):
            output[f"mrr@{k}"] = metric(
                expected_reciprocal_rank(ties, k), version=version, details=details
            )
        else:
            output[f"mrr@{k}"] = not_applicable(
                "no_directly_relevant_gold", version=version, **details
            )
        ideal = sum(
            (2**grade - 1) / math.log2(position + 1)
            for position, grade in enumerate(
                sorted(full_grades, reverse=True)[:k], start=1
            )
        )
        output[f"ndcg@{k}"] = (
            metric(
                tied_dcg(ties, k),
                ideal,
                version=version,
                details={**details, "idcg": ideal},
            )
            if ideal
            else not_applicable("zero_idcg", version=version, **details)
        )
    return output
