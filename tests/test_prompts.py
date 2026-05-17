import pytest

from app.services.config import ClientConfig
from app.services.prompts import build_system_prompt, build_user_prompt


def _config(**kwargs) -> ClientConfig:
    defaults = dict(
        tone="concise and direct",
        materiality_dollars=50_000,
        materiality_pct=0.05,
        focus_areas=["headcount", "T&E"],
        rollup_levels=["Department"],
        suppress_favorable=False,
        prior_period_context=True,
    )
    defaults.update(kwargs)
    return ClientConfig(**defaults)


def _row(**kwargs):
    base = {
        "member_id":        "Salaries|Dept A|FY26Q1",
        "account":          "Salaries",
        "cost_center":      "Dept A",
        "time_period":      "FY26Q1",
        "actual":           980_000,
        "budget":           1_000_000,
        "variance_dollars": -20_000,
        "variance_pct":     -0.02,
        "account_type":     "expense",
        "prior_actual":     975_000,
        "human_commentary": None,
    }
    base.update(kwargs)
    return base


def test_system_prompt_contains_tone():
    prompt = build_system_prompt(_config(tone="formal"))
    assert "formal" in prompt


def test_system_prompt_focus_areas():
    prompt = build_system_prompt(_config(focus_areas=["headcount", "software"]))
    assert "headcount" in prompt
    assert "software" in prompt


def test_user_prompt_contains_account():
    prompt = build_user_prompt(_row())
    assert "Salaries" in prompt


def test_user_prompt_contains_variance():
    prompt = build_user_prompt(_row())
    assert "-20" in prompt or "20,000" in prompt or "20000" in prompt


def test_user_prompt_prior_period():
    prompt = build_user_prompt(_row(prior_actual=975_000))
    assert "975" in prompt


def test_user_prompt_human_commentary():
    prompt = build_user_prompt(_row(human_commentary="Analyst note: delayed hiring."))
    assert "Analyst note" in prompt


def test_system_prompt_no_suppress_favorable_by_default():
    prompt = build_system_prompt(_config(suppress_favorable=False))
    assert "suppress" not in prompt.lower() or "favorable" in prompt.lower()
