"""Pure rule grading of private questions and typed, unmodified learner answers."""

from __future__ import annotations

from decimal import (
    MAX_EMAX,
    MIN_EMIN,
    Context,
    Decimal,
    Inexact,
    ROUND_CEILING,
    ROUND_FLOOR,
    localcontext,
)

from app.learning.contracts import AssessmentDraft
from app.practice.contracts import (
    ClozeAnswer,
    ClozeQuestion,
    NumericAnswer,
    NumericQuestion,
    NumericRubric,
)
from app.practice.identity import normalize_cloze_text
from app.rag.contracts import stable_hash


def _normalize_cloze(text: str, version: str) -> str:
    if version not in {"nfkc-space-v1", "nfkc-space-casefold-v1"}:
        raise ValueError("unsupported_cloze_normalization")
    return normalize_cloze_text(text, version)


def _numeric_matches(value: Decimal, rule: NumericRubric) -> bool:
    # The answer is exactly representable in this fresh context. For any bound
    # b, value <= floor_context(b) iff value <= b (and likewise for >=/ceiling).
    # This also holds for directed overflow/underflow. Inward rounding therefore
    # gives an exact comparison without allocating digits across private rubric
    # exponent gaps. FMA rounds target +/- relative * abs(target) only once.
    context = Context(
        prec=len(value.as_tuple().digits),
        Emin=min(0, value.adjusted()),
        Emax=max(0, value.adjusted()),
        rounding=ROUND_FLOOR,
        traps=[],
    )
    target = rule.target
    if value >= target:
        if value <= context.add(target, rule.absolute_tolerance):
            return True
        return value <= context.fma(rule.relative_tolerance, target.copy_abs(), target)

    context.rounding = ROUND_CEILING
    if value >= context.subtract(target, rule.absolute_tolerance):
        return True
    return value >= context.fma(
        rule.relative_tolerance.copy_negate(), target.copy_abs(), target
    )


def _criterion_result(
    criterion_id: str,
    matched: bool,
    rationale: str,
    evidence_refs: list[str],
    answer_quote: str,
) -> dict:
    return {
        "criterion_id": criterion_id,
        "credit": "full" if matched else "none",
        "rationale": rationale,
        "evidence_refs": list(evidence_refs),
        "answer_quotes": [answer_quote],
    }


def grade_rules(
    question: ClozeQuestion | NumericQuestion,
    answer: ClozeAnswer | NumericAnswer,
) -> AssessmentDraft:
    """Return an exact deterministic assessment; reject invalid submissions."""
    criteria = []
    if isinstance(question, ClozeQuestion) and question.type == "cloze":
        if not isinstance(answer, ClozeAnswer) or answer.type != "cloze":
            raise ValueError("answer_type_mismatch")
        slot_ids = [slot.blank_id for slot in question.rubric.slots]
        answer_ids = [blank.blank_id for blank in answer.blanks]
        if (
            len(answer_ids) != len(set(answer_ids))
            or len(slot_ids) != len(set(slot_ids))
            or set(answer_ids) != set(slot_ids)
        ):
            raise ValueError("blank_ids_mismatch")
        responses = {blank.blank_id: blank.text for blank in answer.blanks}
        weights = []
        for slot in question.rubric.slots:
            raw_text = responses[slot.blank_id]
            version = question.rubric.normalization
            normalized = _normalize_cloze(raw_text, version)
            matched = normalized in {
                _normalize_cloze(accepted, version) for accepted in slot.accepted
            }
            if matched:
                weights.append(slot.weight)
            criteria.append(
                _criterion_result(
                    slot.blank_id,
                    matched,
                    "符合该空声明的答案。" if matched else "未符合该空声明的答案。",
                    question.citation_refs,
                    raw_text,
                )
            )

        # Valid P01 weights are positive, total exactly one, and have at most
        # five slots. Coefficient precision plus carry digits sums any subset
        # exactly; a fresh context avoids inheriting caller traps or limits.
        precision = (
            max(len(slot.weight.as_tuple().digits) for slot in question.rubric.slots)
            + 2
        )
        with localcontext(
            Context(prec=precision, Emin=MIN_EMIN, Emax=MAX_EMAX)
        ) as context:
            context.traps[Inexact] = True
            score = sum(weights, Decimal("0"))
    elif isinstance(question, NumericQuestion) and question.type == "numeric":
        if not isinstance(answer, NumericAnswer) or answer.type != "numeric":
            raise ValueError("answer_type_mismatch")
        # Reapply P01's strict grammar/range even if a caller bypassed Pydantic
        # with model_construct/model_copy. Validation preserves the raw string.
        validated = NumericAnswer.model_validate(
            {"type": answer.type, "value": answer.value, "unit": answer.unit}
        )
        if validated.unit not in question.rubric.unit_aliases:
            raise ValueError("unsupported_numeric_unit")
        matched = _numeric_matches(Decimal(validated.value), question.rubric)
        score = Decimal("1") if matched else Decimal("0")
        criteria.append(
            _criterion_result(
                "numeric",
                matched,
                "数值在规定容差内。" if matched else "数值超出规定容差。",
                question.citation_refs,
                answer.value,
            )
        )
    else:
        raise ValueError("unsupported_question_type")

    return AssessmentDraft(
        status="graded",
        score=score,
        source="deterministic",
        confirmation="confirmed",
        grader_version="rules-v1",
        rubric_version=question.rubric.version,
        rubric_hash=stable_hash(question.rubric.model_dump(mode="json")),
        feedback=question.rubric.explanation,
        evidence_refs=list(question.citation_refs),
        criterion_results=criteria,
        independent_eligible=False,
    )
