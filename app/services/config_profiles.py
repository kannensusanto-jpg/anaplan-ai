from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.form_config import ConfigProfile, FormConfig
from app.services.config import ClientConfig

_DEFAULTS = [
    {
        "profile_name":        "P&L",
        "tone":                "executive summary",
        "materiality_dollars": 50_000,
        "materiality_pct":     0.05,
        "focus_areas":         "revenue, gross margin, opex, headcount",
        "rollup_levels":       "Department, Division",
        "suppress_favorable":  False,
        "prior_period_context": True,
        "is_global":           True,
    },
    {
        "profile_name":        "Headcount",
        "tone":                "concise and direct",
        "materiality_dollars": 10_000,
        "materiality_pct":     0.03,
        "focus_areas":         "headcount, salaries, benefits, contractors",
        "rollup_levels":       "Department",
        "suppress_favorable":  False,
        "prior_period_context": True,
        "is_global":           True,
    },
    {
        "profile_name":        "CapEx",
        "tone":                "concise and direct",
        "materiality_dollars": 100_000,
        "materiality_pct":     0.05,
        "focus_areas":         "capital expenditure, projects, depreciation",
        "rollup_levels":       "Project, Category",
        "suppress_favorable":  False,
        "prior_period_context": True,
        "is_global":           True,
    },
    {
        "profile_name":        "Balance Sheet",
        "tone":                "concise and direct",
        "materiality_dollars": 100_000,
        "materiality_pct":     0.05,
        "focus_areas":         "assets, liabilities, equity, working capital",
        "rollup_levels":       "",
        "suppress_favorable":  False,
        "prior_period_context": True,
        "is_global":           True,
    },
    {
        "profile_name":        "Cash Flow",
        "tone":                "concise and direct",
        "materiality_dollars": 50_000,
        "materiality_pct":     0.05,
        "focus_areas":         "operating, investing, financing activities",
        "rollup_levels":       "",
        "suppress_favorable":  False,
        "prior_period_context": True,
        "is_global":           True,
    },
]


async def seed_default_profiles(db: AsyncSession) -> None:
    for data in _DEFAULTS:
        result = await db.execute(
            select(ConfigProfile).where(
                ConfigProfile.profile_name == data["profile_name"],
                ConfigProfile.is_global.is_(True),
                ConfigProfile.client_id.is_(None),
            )
        )
        if result.scalar_one_or_none() is None:
            db.add(ConfigProfile(**data))
    await db.commit()


async def build_client_config(
    db: AsyncSession, form_config: FormConfig, client_id: str
) -> ClientConfig:
    """
    Merge the form's base profile with any per-form overrides to produce
    a ClientConfig ready for the generation pipeline.
    """
    result = await db.execute(
        select(ConfigProfile).where(
            ConfigProfile.profile_name == form_config.profile_name,
            or_(
                ConfigProfile.client_id.is_(None),
                ConfigProfile.client_id == client_id,
            ),
        ).order_by(ConfigProfile.is_global.asc())  # tenant profile wins over global
    )
    profile = result.scalars().first()

    if profile is None:
        # Fallback: use P&L global defaults
        tone                 = "concise and direct"
        materiality_dollars  = 50_000.0
        materiality_pct      = 0.05
        focus_areas_str      = ""
        rollup_levels_str    = ""
        suppress_favorable   = False
        prior_period_context = True
    else:
        tone                 = profile.tone
        materiality_dollars  = profile.materiality_dollars
        materiality_pct      = profile.materiality_pct
        focus_areas_str      = profile.focus_areas or ""
        rollup_levels_str    = profile.rollup_levels or ""
        suppress_favorable   = profile.suppress_favorable
        prior_period_context = profile.prior_period_context

    # Apply per-form overrides (any key from ConfigProfile can be overridden)
    overrides = form_config.config_overrides or {}
    if "TONE" in overrides:
        tone = overrides["TONE"]
    if "MATERIALITY_THRESHOLD_$" in overrides:
        materiality_dollars = float(overrides["MATERIALITY_THRESHOLD_$"])
    if "MATERIALITY_THRESHOLD_%" in overrides:
        materiality_pct = float(overrides["MATERIALITY_THRESHOLD_%"])
    if "FOCUS_AREAS" in overrides:
        focus_areas_str = overrides["FOCUS_AREAS"]
    if "ROLLUP_LEVELS" in overrides:
        rollup_levels_str = overrides["ROLLUP_LEVELS"]
    if "SUPPRESS_FAVORABLE" in overrides:
        suppress_favorable = str(overrides["SUPPRESS_FAVORABLE"]).upper() == "TRUE"
    if "PRIOR_PERIOD_CONTEXT" in overrides:
        prior_period_context = str(overrides["PRIOR_PERIOD_CONTEXT"]).upper() != "FALSE"

    return ClientConfig(
        tone=tone,
        materiality_dollars=materiality_dollars,
        materiality_pct=materiality_pct,
        focus_areas=[s.strip() for s in focus_areas_str.split(",") if s.strip()],
        rollup_levels=[s.strip() for s in rollup_levels_str.split(",") if s.strip()],
        suppress_favorable=suppress_favorable,
        prior_period_context=prior_period_context,
    )


async def get_profiles_for_client(db: AsyncSession, client_id: str) -> list[ConfigProfile]:
    result = await db.execute(
        select(ConfigProfile)
        .where(
            ConfigProfile.client_id.is_(None) | (ConfigProfile.client_id == client_id)
        )
        .order_by(ConfigProfile.is_global.desc(), ConfigProfile.profile_name)
    )
    return result.scalars().all()
