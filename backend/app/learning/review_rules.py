"""Deterministic review-rules-v1 product rules, not an efficacy estimate."""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.learning.contracts import ConceptState, LearningOutcome, ReviewDecision


RULE_VERSION = "review-rules-v1"
_INTERVAL_DAYS = (1, 3, 7, 14)


def _local_due(activity_date: date, days: int, zone: ZoneInfo) -> datetime:
    due_date = activity_date + timedelta(days=days)
    return datetime.combine(due_date, time(9), tzinfo=zone).astimezone(UTC)


def next_schedule(
    state: ConceptState,
    outcome: LearningOutcome,
    now_utc: datetime,
    timezone: str,
) -> ReviewDecision:
    """Recommend a schedule without changing the supplied learning facts.

    Replay callers supply the original completion time and frozen timezone.
    Retained due times are never reinterpreted under a different timezone.
    Non-final results preserve the schedule. Confirmed wrong/partial results
    reset it before eligibility or repeat checks; helped/ineligible full scores
    also schedule the next day before repeat suppression applies.

    ``advance`` means a numeric stage increase, not any due-time change. An
    independent success at stage 4 keeps ``advance=False`` but refreshes the
    14-day due and returns ``independent_success_at_cap`` so consumers can
    still record qualifying success evidence separately from advancement.
    """
    if now_utc.tzinfo is None or now_utc.utcoffset() is None:
        raise ValueError("now_utc must be timezone-aware")
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone name") from exc

    if outcome.status != "graded" or outcome.confirmation != "confirmed":
        return ReviewDecision(
            stage=state.stage,
            due_at=state.due_at,
            reason="not_confirmed",
            advance=False,
        )

    activity_date = now_utc.astimezone(zone).date()
    if outcome.score < 1:
        return ReviewDecision(
            stage=0,
            due_at=_local_due(activity_date, 1, zone),
            reason="confirmed_wrong_or_partial",
            advance=False,
        )

    if outcome.help_usage != "none" or not outcome.independent_eligible:
        return ReviewDecision(
            stage=state.stage,
            due_at=_local_due(activity_date, 1, zone),
            reason="not_independent",
            advance=False,
        )

    repeat_reason = None
    if state.last_activity_local_date == activity_date:
        repeat_reason = "same_day_repeat"
    elif set(outcome.question_versions).intersection(state.seen_question_versions):
        repeat_reason = "seen_question_version"
    if repeat_reason is not None:
        return ReviewDecision(
            stage=state.stage,
            due_at=state.due_at or _local_due(activity_date, 1, zone),
            reason=repeat_reason,
            advance=False,
        )

    next_stage = min(state.stage + 1, 4)
    advance = next_stage > state.stage
    return ReviewDecision(
        stage=next_stage,
        due_at=_local_due(activity_date, _INTERVAL_DAYS[next_stage - 1], zone),
        reason="independent_success" if advance else "independent_success_at_cap",
        advance=advance,
    )
