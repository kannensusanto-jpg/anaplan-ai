from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.form_config import ConfigProfile

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


async def get_profiles_for_client(db: AsyncSession, client_id: str) -> list[ConfigProfile]:
    result = await db.execute(
        select(ConfigProfile)
        .where(
            ConfigProfile.client_id.is_(None) | (ConfigProfile.client_id == client_id)
        )
        .order_by(ConfigProfile.is_global.desc(), ConfigProfile.profile_name)
    )
    return result.scalars().all()
