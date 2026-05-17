from unittest.mock import AsyncMock, patch

import pytest

from app.services.config import ClientConfig
from app.services.generator import generate_commentary


def _config() -> ClientConfig:
    return ClientConfig(
        tone="concise",
        materiality_dollars=50_000,
        materiality_pct=0.05,
        focus_areas=[],
        rollup_levels=[],
        suppress_favorable=False,
        prior_period_context=True,
    )


def _row(account, parent=None, **kwargs):
    mid = f"{account}|Dept A|FY26Q1"
    base = {
        "member_id":        mid,
        "account":          account,
        "cost_center":      "Dept A",
        "time_period":      "FY26Q1",
        "actual":           900_000,
        "budget":           1_000_000,
        "variance_dollars": -100_000,
        "variance_pct":     -0.10,
        "account_type":     "expense",
        "prior_actual":     950_000,
        "human_commentary": None,
        "parent_member_id": parent,
    }
    base.update(kwargs)
    return base


@pytest.mark.asyncio
async def test_leaf_commentary_generated():
    rows = [_row("Salaries"), _row("Benefits")]
    hierarchy = {}

    fake_response = ("Salaries over budget by 10%.", {"input_tokens": 100, "output_tokens": 20,
                                                       "cache_read_tokens": 0, "cache_creation_tokens": 0})
    with patch("app.services.generator._call_claude", new_callable=AsyncMock,
               return_value=fake_response):
        commentary, usage = await generate_commentary(_config(), rows, hierarchy)

    assert "Salaries|Dept A|FY26Q1" in commentary
    assert "Benefits|Dept A|FY26Q1" in commentary
    assert usage["input_tokens"] == 200  # 2 rows × 100


@pytest.mark.asyncio
async def test_rollup_generated_after_leaves():
    leaf1  = _row("Salaries", parent="Total Payroll")
    leaf2  = _row("Benefits", parent="Total Payroll")
    rollup = _row("Total Payroll")

    hierarchy = {
        "Total Payroll|Dept A|FY26Q1": [
            "Salaries|Dept A|FY26Q1",
            "Benefits|Dept A|FY26Q1",
        ]
    }
    rows = [leaf1, leaf2, rollup]

    call_order = []

    async def fake_call(system_prompt, row, is_rollup=False):
        call_order.append((row["account"], is_rollup))
        return (f"Commentary for {row['account']}", {
            "input_tokens": 100, "output_tokens": 20,
            "cache_read_tokens": 0, "cache_creation_tokens": 0,
        })

    with patch("app.services.generator._call_claude", side_effect=fake_call):
        commentary, _ = await generate_commentary(_config(), rows, hierarchy)

    rollup_call = next(c for c in call_order if c[0] == "Total Payroll")
    leaf_calls  = [c for c in call_order if c[0] != "Total Payroll"]

    assert rollup_call[1] is True
    assert all(not c[1] for c in leaf_calls)

    rollup_idx = call_order.index(rollup_call)
    leaf_idxes = [call_order.index(c) for c in leaf_calls]
    assert all(i < rollup_idx for i in leaf_idxes), "Rollup must come after leaves"
