from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, JSON, String

from app.models.base import Base


class ConfigProfile(Base):
    __tablename__ = "config_profiles"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    client_id           = Column(String, nullable=True)   # NULL = global default
    profile_name        = Column(String, nullable=False)
    tone                = Column(String, default="concise and direct")
    materiality_dollars = Column(Float,  default=50_000)
    materiality_pct     = Column(Float,  default=0.05)
    focus_areas         = Column(String, default="")      # comma-separated
    rollup_levels       = Column(String, default="")
    suppress_favorable  = Column(Boolean, default=False)
    prior_period_context = Column(Boolean, default=True)
    is_global           = Column(Boolean, default=False)  # built-in default profile
    created_at          = Column(DateTime, default=datetime.utcnow)


class FormConfig(Base):
    __tablename__ = "form_configs"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    client_id   = Column(String, nullable=False)
    form_id     = Column(String, nullable=False)   # Anaplan view ID or user-assigned slug
    form_name   = Column(String, nullable=False)
    form_source = Column(String, default="excel")  # "anaplan" | "excel"
    profile_name = Column(String, nullable=False)  # matches ConfigProfile.profile_name

    # Per-form config overrides (any key from ConfigProfile can be overridden)
    config_overrides = Column(JSON, default=dict)

    # Maps semantic role → Anaplan dimension name.
    # Known roles: "account", "time", "version", "entity", "commentary".
    # Add any other dimension present on the form (e.g. "product", "region").
    # Fixed-value context dimensions go in page_selectors.
    dimension_roles = Column(JSON, default=dict)

    # Version member names within the version dimension
    actual_version_member = Column(String, default="Actual")
    budget_version_member = Column(String, default="Budget")

    # Excel grid specifics
    header_rows     = Column(Integer, default=1)
    account_col     = Column(Integer, default=0)      # 0-based column index
    entity_col      = Column(Integer, nullable=True)   # 0-based; None = use page_selectors/tab name
    page_selectors  = Column(JSON, default=dict)       # {"Cost Center": "Dept A"}
    column_mapping  = Column(JSON, default=dict)       # see grid_parser for format

    # Anaplan specifics
    view_id          = Column(String, nullable=True)
    import_action_id = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
