import pytest

from app.services.config import ClientConfig
from app.services.materiality import apply_materiality_filter


def _config(**kwargs) -> ClientConfig:
    defaults = dict(
        tone="concise",
        materiality_dollars=50_000,
        materiality_pct=0.05,
        focus_areas=[],
        rollup_levels=[],
        suppress_favorable=False,
        prior_period_context=True,
    )
    defaults.update(kwargs)
    return ClientConfig(**defaults)


def _row(account="Sales", actual=900_000, budget=1_000_000, account_type="expense"):
    return {
        "member_id":        f"{account}|Dept A|FY26Q1",
        "account":          account,
        "cost_center":      "Dept A",
        "time_period":      "FY26Q1",
        "actual":           actual,
        "budget":           budget,
        "variance_dollars": actual - budget,
        "variance_pct":     (actual - budget) / budget if budget else 0,
        "account_type":     account_type,
        "prior_actual":     0,
        "human_commentary": None,
        "parent_member_id": None,
    }


def test_over_materiality_passes():
    rows   = [_row(actual=900_000, budget=1_000_000)]  # -100k, 10%
    result = apply_materiality_filter(rows, _config())
    assert len(result.generate) == 1
    assert len(result.skipped)  == 0


def test_below_dollar_threshold_skipped():
    rows   = [_row(actual=995_000, budget=1_000_000)]  # -5k, 0.5%
    result = apply_materiality_filter(rows, _config())
    assert len(result.skipped) == 1
    assert "materiality" in result.skipped[0][1].lower()


def test_favorable_expense_suppressed():
    config = _config(suppress_favorable=True)
    rows   = [_row(actual=900_000, budget=1_000_000, account_type="expense")]
    # expense: actual < budget = favorable
    result = apply_materiality_filter(rows, config)
    assert len(result.skipped) == 1
    assert "favorable" in result.skipped[0][1].lower()


def test_favorable_revenue_unfavorable():
    # revenue: actual < budget = UNfavorable
    config = _config(suppress_favorable=True)
    rows   = [_row(actual=900_000, budget=1_000_000, account_type="revenue")]
    result = apply_materiality_filter(rows, config)
    assert len(result.generate) == 1


def test_zero_budget_handled():
    rows   = [_row(actual=10_000, budget=0)]
    result = apply_materiality_filter(rows, _config())
    assert len(result.skipped) == 1  # variance_pct = 0 → below materiality_pct threshold
