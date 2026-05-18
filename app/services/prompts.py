from app.services.config import ClientConfig


def build_dataset_summary(rows: list[dict], page_context: dict | None = None) -> str:
    """
    Analyse the full row set and return a concise summary that gives Claude
    pattern awareness before it generates individual row commentary.
    """
    if not rows:
        return ""

    total_actual   = sum(r["actual"]           for r in rows)
    total_budget   = sum(r["budget"]           for r in rows)
    total_variance = sum(r["variance_dollars"] for r in rows)
    var_pct        = total_variance / total_budget if total_budget else 0.0
    direction      = "UNFAV" if total_variance > 0 else "FAV"

    # Top 3 unfavorable and favorable drivers
    unfav = sorted([r for r in rows if r["variance_dollars"] > 0],
                   key=lambda r: r["variance_dollars"], reverse=True)[:3]
    fav   = sorted([r for r in rows if r["variance_dollars"] < 0],
                   key=lambda r: r["variance_dollars"])[:3]

    def _fmt_driver(r: dict) -> str:
        ctx = r.get("dim_context", {})
        dims = ", ".join(f"{k}: {v}" for k, v in ctx.items()) if ctx else r.get("cost_center", "")
        return (
            f"  {r['account']} ({dims or r['cost_center']}): "
            f"${r['variance_dollars']:+,.0f} ({r['variance_pct']:+.1%})"
        )

    # Cross-entity pattern: accounts that are over/under budget across multiple entities
    over_entities:  dict[str, set] = {}
    under_entities: dict[str, set] = {}
    for r in rows:
        entity = r.get("cost_center") or ""
        if r["variance_dollars"] > 0:
            over_entities.setdefault(r["account"], set()).add(entity)
        elif r["variance_dollars"] < 0:
            under_entities.setdefault(r["account"], set()).add(entity)

    patterns: list[str] = []
    for acct, entities in over_entities.items():
        if len(entities) > 1:
            patterns.append(
                f"  {acct} over budget across {len(entities)} entities "
                f"({', '.join(sorted(entities))})"
            )
    for acct, entities in under_entities.items():
        if len(entities) > 1:
            patterns.append(
                f"  {acct} under budget across {len(entities)} entities "
                f"({', '.join(sorted(entities))})"
            )

    # Distinct dimension values
    entities = sorted({r.get("cost_center") for r in rows if r.get("cost_center")})
    periods  = sorted({r.get("time_period") for r in rows if r.get("time_period")})

    ctx_line = ""
    if page_context:
        ctx_line = "  " + " | ".join(f"{k}: {v}" for k, v in page_context.items()) + "\n"

    lines = [
        "DATASET OVERVIEW",
        f"  Total Actual: ${total_actual:,.0f} | Budget: ${total_budget:,.0f} | "
        f"Variance: ${total_variance:+,.0f} ({var_pct:+.1%}) {direction}",
    ]
    if ctx_line:
        lines.append(ctx_line.rstrip())
    if len(entities) > 1:
        lines.append(f"  Entities: {', '.join(entities)}")
    if len(periods) > 1:
        lines.append(f"  Periods: {', '.join(periods)}")
    if unfav:
        lines.append("TOP UNFAVORABLE DRIVERS")
        lines += [_fmt_driver(r) for r in unfav]
    if fav:
        lines.append("TOP FAVORABLE DRIVERS")
        lines += [_fmt_driver(r) for r in fav]
    if patterns:
        lines.append("CROSS-ENTITY PATTERNS")
        lines += patterns

    return "\n".join(lines)


def build_system_prompt(config: ClientConfig, dataset_summary: str = "") -> str:
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

    summary_block = f"\n\n{dataset_summary}" if dataset_summary else ""

    return f"""You are an FP&A analyst writing variance commentary inside a financial planning system.

You write the AI Commentary column. The human analyst's column is separate — never reference it.

TONE: {config.tone}
FOCUS AREAS: {focus}
PRIOR PERIOD: {prior_period}
FAVORABLE VARIANCES: {favorable_rule}

RULES:
- 1–3 sentences per intersection
- Lead with the dollar or percent variance, then the primary driver
- Reference cross-entity or cross-period patterns where relevant (use the dataset overview below)
- For rollup members, synthesize child drivers — do not repeat each child line verbatim
- No filler phrases ("it is worth noting", "it should be mentioned")
- Output commentary text only — no labels, no JSON, no explanation of your reasoning{summary_block}"""


def build_user_prompt(row: dict, page_context: dict | None = None) -> str:
    # Extra dimension context: page selectors + any per-row dim_context
    ctx: dict = {}
    if page_context:
        ctx.update(page_context)
    if row.get("dim_context"):
        ctx.update(row["dim_context"])

    ctx_lines = "".join(f"{k}: {v}\n" for k, v in ctx.items()) if ctx else ""

    return (
        f"Account: {row['account']}\n"
        f"Cost Centre: {row['cost_center']}\n"
        f"Period: {row['time_period']}\n"
        + ctx_lines +
        f"Actual: ${row['actual']:,.0f}\n"
        f"Budget: ${row['budget']:,.0f}\n"
        f"Variance $: ${row['variance_dollars']:,.0f} ({row['variance_pct']:+.1%})\n"
        f"Prior Period Actual: ${row['prior_actual']:,.0f}\n"
        f"Account Type: {row.get('account_type', 'expense')}\n"
        f"Notes from analyst: {row.get('human_commentary') or 'None'}"
    )
