from app.services.config import ClientConfig


def build_system_prompt(config: ClientConfig) -> str:
    focus = ", ".join(config.focus_areas) if config.focus_areas else "all variance drivers"
    favorable_rule = (
        "Note favorable variances in one phrase; do not elaborate."
        if config.suppress_favorable
        else "Explain both favorable and unfavorable variances with equal depth."
    )
    prior_period = (
        "Include prior period comparison where it adds context."
        if config.prior_period_context
        else "Focus on budget vs. actual only. Do not reference prior periods."
    )

    return f"""You are an FP&A analyst writing variance commentary inside a financial planning system.

You write the AI Commentary column. The human analyst's column is separate — never reference it.

TONE: {config.tone}
FOCUS AREAS: {focus}
PRIOR PERIOD: {prior_period}
FAVORABLE VARIANCES: {favorable_rule}

RULES:
- 1–3 sentences per intersection
- Lead with the dollar or percent variance, then the primary driver
- For rollup members, synthesize child drivers — do not repeat each child line verbatim
- No filler phrases ("it is worth noting", "it should be mentioned")
- Output commentary text only — no labels, no JSON, no explanation of your reasoning"""


def build_user_prompt(row: dict) -> str:
    return (
        f"Account: {row['account']}\n"
        f"Cost Center: {row['cost_center']}\n"
        f"Actual: ${row['actual']:,.0f}\n"
        f"Budget: ${row['budget']:,.0f}\n"
        f"Variance $: ${row['variance_dollars']:,.0f} ({row['variance_pct']:+.1%})\n"
        f"Prior Period Actual: ${row['prior_actual']:,.0f}\n"
        f"Notes from analyst: {row.get('human_commentary') or 'None'}"
    )
