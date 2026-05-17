from dataclasses import dataclass

from app.services.config import ClientConfig


@dataclass
class FilterResult:
    generate: list[dict]
    skipped:  list[tuple[dict, str]]


def apply_materiality_filter(rows: list[dict], config: ClientConfig) -> FilterResult:
    generate, skipped = [], []
    for row in rows:
        reason = _skip_reason(row, config)
        if reason:
            skipped.append((row, reason))
        else:
            generate.append(row)
    return FilterResult(generate=generate, skipped=skipped)


def _skip_reason(row: dict, config: ClientConfig) -> str | None:
    variance_abs = abs(row["variance_dollars"])
    variance_pct = abs(row["variance_pct"])
    is_favorable = _is_favorable(row)

    if is_favorable and config.suppress_favorable:
        return "suppressed: favorable variance"

    if variance_abs < config.materiality_dollars and variance_pct < config.materiality_pct:
        return (
            f"below materiality: "
            f"${variance_abs:,.0f} < ${config.materiality_dollars:,.0f} "
            f"and {variance_pct:.1%} < {config.materiality_pct:.1%}"
        )
    return None


def _is_favorable(row: dict) -> bool:
    if row.get("account_type") == "revenue":
        return row["variance_dollars"] > 0
    return row["variance_dollars"] < 0
