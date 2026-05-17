from dataclasses import dataclass, field


@dataclass
class ClientConfig:
    tone: str
    materiality_dollars: float
    materiality_pct: float
    focus_areas: list[str]
    rollup_levels: list[str]
    suppress_favorable: bool
    prior_period_context: bool
