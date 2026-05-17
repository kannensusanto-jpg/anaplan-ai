from datetime import datetime

from pydantic import BaseModel


class ConfigProfileCreate(BaseModel):
    profile_name:         str
    tone:                 str = "concise and direct"
    materiality_dollars:  float = 50_000
    materiality_pct:      float = 0.05
    focus_areas:          str = ""
    rollup_levels:        str = ""
    suppress_favorable:   bool = False
    prior_period_context: bool = True


class ConfigProfileOut(ConfigProfileCreate):
    is_global:  bool
    client_id:  str | None
    created_at: datetime

    class Config:
        from_attributes = True


class FormConfigIn(BaseModel):
    form_id:    str
    form_name:  str
    form_source: str = "excel"          # "anaplan" | "excel"
    profile_name: str

    config_overrides: dict = {}

    # Anaplan dimension names
    dim_account:    str | None = None
    dim_time:       str | None = None
    dim_version:    str | None = None
    dim_entity:     str | None = None
    dim_commentary: str | None = None

    actual_version_member: str = "Actual"
    budget_version_member: str = "Budget"

    # Excel grid specifics
    header_rows:    int = 1
    account_col:    int = 0
    page_selectors: dict = {}
    column_mapping: dict = {}

    # Anaplan specifics
    view_id:          str | None = None
    import_action_id: str | None = None


class FormConfigOut(FormConfigIn):
    id:         int
    client_id:  str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
