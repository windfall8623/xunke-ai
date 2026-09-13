"""Learning metrics observation (E02): explicit denominators, null without samples."""

from datetime import UTC, datetime, timedelta

import pytest

from app.services.learning_metrics_service import metric, observed_rate


def test_observed_rate_boundaries():
    assert observed_rate(0, 0) is None
    assert observed_rate(1, 2) == 0.5
    with pytest.raises(ValueError):
        observed_rate(-1, 2)
    with pytest.raises(ValueError):
        observed_rate(3, 2)


def test_metric_records_explain_missing_samples():
    empty = metric(None, 0, detail="样本不足")
    assert empty["rate"] is None and empty["denominator"] == 0
    known = metric(1, 4)
    assert known["rate"] == 0.25 and known["unknown_count"] == 0


@pytest.mark.asyncio
async def test_summary_window_shape(learner):
    api, session = learner
    owner = session["user"]["id"]
    from app.services.learning_metrics_service import summarize_learning_metrics

    end = datetime.now(UTC)
    summary = await summarize_learning_metrics(owner, end - timedelta(days=7), end)
    assert summary["first_lesson_completion"]["rate"] is None
    assert summary["wait_and_recovery"]["task_retries"] == 0
    assert "unknown" in summary["cost_benefit"]["note"]
