"""Deterministic structure, scope, answer-set, coverage and quotation checks.

Passing these rules is not a claim of semantic correctness. Production additionally
uses the separately budgeted semantic validator, and evaluation keeps judge/human
truth separate from this generation-time model check.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from pydantic import ValidationError

from app.rag.contracts import QuizPayload, ValidationResult
from app.rag.scope import evidence_in_scope


def validate_quiz_artifact(payload, spec, pack) -> ValidationResult:
    try:
        quiz = QuizPayload.model_validate(
            payload.model_dump() if hasattr(payload, "model_dump") else payload
        )
    except ValidationError as exc:
        return ValidationResult(
            passed=False,
            errors=[
                "schema_invalid:" + ".".join(map(str, e["loc"]))
                for e in exc.errors(include_input=False)
            ],
        )
    errors = []
    if len(quiz.questions) != spec.question_count:
        errors.append("question_count_mismatch")
    if len({q.id for q in quiz.questions}) != len(quiz.questions):
        errors.append("duplicate_question_id")
    provided = set(pack.provided_evidence_ids)
    evidence = {e.evidence_id: e for e in pack.evidence}
    if provided != set(evidence):
        errors.append("provided_evidence_set_mismatch")
    for e in pack.evidence:
        if not evidence_in_scope(e, pack.resolved_scope):
            errors.append("evidence_outside_scope")
    stems = []
    quotas = Counter()
    plan = {t.target_id: t for t in pack.coverage.targets} if pack.coverage else {}
    for number, question in enumerate(quiz.questions, 1):
        prefix = f"question_{number}:"
        keys = [o.key for o in question.options]
        answers = question.answer
        if len(set(keys)) != len(keys) or any(
            not re.fullmatch(r"[A-H]", k) for k in keys
        ):
            errors.append(prefix + "invalid_option_keys")
        if len(set(answers)) != len(answers) or not set(answers) <= set(keys):
            errors.append(prefix + "invalid_answer_set")
        if question.type in ("single", "judge") and len(answers) != 1:
            errors.append(prefix + "single_answer_required")
        if question.type == "multiple" and len(answers) < 2:
            errors.append(prefix + "multiple_answers_required")
        if question.type == "judge" and [(o.key, o.text) for o in question.options] != [
            ("A", "正确"),
            ("B", "错误"),
        ]:
            errors.append(prefix + "invalid_judge_options")
        if spec.difficulty != "mixed" and question.difficulty != spec.difficulty:
            errors.append(prefix + "difficulty_mismatch")
        stem = re.sub(r"[\W_]+", "", question.stem).casefold()
        if any(
            stem == other
            or (
                min(len(stem), len(other)) > 12
                and SequenceMatcher(None, stem, other).ratio() > 0.95
            )
            for other in stems
        ):
            errors.append(prefix + "duplicate_question")
        stems.append(stem)
        refs = question.citation_refs
        if len(refs) != len(set(refs)) or not set(refs) <= provided:
            errors.append(prefix + "unknown_or_duplicate_citation")
        if pack.status != "model_only":
            if not refs:
                errors.append(prefix + "missing_citation")
            source_quotes = [evidence[r].excerpt for r in refs if r in evidence]
            if not question.support_quotes or any(
                not quote.strip()
                or not any(quote in excerpt for excerpt in source_quotes)
                for quote in question.support_quotes
            ):
                errors.append(prefix + "unsupported_support_quote")
            if (
                question.type == "judge"
                and answers == ["B"]
                and any(
                    marker in question.explanation
                    for marker in (
                        "未提及所以",
                        "没有提到所以",
                        "未提及，因此错误",
                        "无法判断所以错误",
                    )
                )
            ):
                errors.append(prefix + "absence_is_not_false_counterevidence")
        elif refs or question.support_quotes:
            errors.append(prefix + "model_only_cannot_claim_citations")
        if plan:
            target = plan.get(question.coverage_target_id)
            if target is None:
                errors.append(prefix + "unknown_coverage_target")
            else:
                quotas[target.target_id] += 1
                if pack.status != "model_only" and not set(refs) & set(
                    target.evidence_ids
                ):
                    errors.append(prefix + "coverage_evidence_mismatch")
    for target_id, target in plan.items():
        if quotas[target_id] != target.question_quota:
            errors.append("coverage_quota_mismatch:" + target_id)
    return ValidationResult(passed=not errors, errors=errors)
