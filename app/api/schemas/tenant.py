from pydantic import BaseModel, HttpUrl


class TenantCreate(BaseModel):
    company_name:       str
    workspace_id:       str
    model_id:           str
    config_module_id:   str
    target_module_id:   str
    import_action_id:   str
    commentary_file_id: str
    client_id:          str
    client_secret:      str
    webhook_url:        str | None = None


class TenantCreated(BaseModel):
    client_id:   str
    api_key:     str
    company_name: str


class TenantSummary(BaseModel):
    client_id:    str
    company_name: str
    workspace_id: str
    model_id:     str
    has_webhook:  bool

    class Config:
        from_attributes = True


class KeyRotated(BaseModel):
    client_id: str
    api_key:   str
