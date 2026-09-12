import pytest


def test_all_llm_attempts_consume_budget_before_dispatch():
    from app.rag.budget import BudgetLedger
    from app.rag.contracts import BudgetLimits
    from app.rag.errors import BudgetExceeded

    budget = BudgetLedger(BudgetLimits(max_llm_calls=2))
    budget.reserve("llm", input_tokens=10)
    budget.reserve("llm", input_tokens=15)
    with pytest.raises(BudgetExceeded):
        budget.reserve("llm")
    assert budget.usage.llm_calls == 2
    assert budget.usage.input_tokens == 25


def test_missing_cost_estimate_cannot_bypass_monetary_cap():
    from app.rag.budget import BudgetLedger
    from app.rag.contracts import BudgetLimits
    from app.rag.errors import BudgetExceeded

    budget = BudgetLedger(BudgetLimits(max_cost_usd=0.01))
    with pytest.raises(BudgetExceeded):
        budget.reserve("llm")
    budget.reserve("llm", estimated_cost_usd=0.006)
    with pytest.raises(BudgetExceeded):
        budget.reserve("embedding", estimated_cost_usd=0.006)


def test_elapsed_deadline_prevents_dispatch():
    from app.rag.budget import BudgetLedger
    from app.rag.contracts import BudgetLimits
    from app.rag.errors import BudgetExceeded

    now = [10.0]
    ledger = BudgetLedger(BudgetLimits(deadline_seconds=2), clock=lambda: now[0])
    now[0] = 13.0
    with pytest.raises(BudgetExceeded):
        ledger.reserve("search")
