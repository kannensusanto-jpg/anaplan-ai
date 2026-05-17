import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant, get_db
from app.models.form_config import FormConfig
from app.models.tenant import Tenant
from app.services.auth import AnaplanAuthService
from app.services.config_profiles import build_client_config
from app.services.generator import generate_commentary
from app.services.materiality import apply_materiality_filter
from app.services.preview_store import save_preview
from app.core.config import settings

router = APIRouter(prefix="/v1/anaplan", tags=["anaplan"])

_auth = AnaplanAuthService(settings.ENCRYPTION_KEY.encode())


@router.get("/views")
async def list_anaplan_views(tenant: Tenant = Depends(get_current_tenant)):
    """List all views available in the tenant's Anaplan model."""
    from app.services.anaplan_client import AnaplanClient

    try:
        token   = await _auth.get_token(tenant.client_id, tenant.credentials)
        anaplan = AnaplanClient(tenant.workspace_id, tenant.model_id, token)
        views   = anaplan.list_views()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Anaplan error: {exc}")

    return {"views": views}


@router.post("/generate-form")
async def generate_from_anaplan_form(
    body: dict,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate commentary for a registered Anaplan-source form.
    Body: {"form_id": "<form_id>"}
    """
    form_id = body.get("form_id")
    if not form_id:
        raise HTTPException(status_code=400, detail="form_id is required")

    result = await db.execute(
        select(FormConfig).where(
            FormConfig.client_id == tenant.client_id,
            FormConfig.form_id == form_id,
        )
    )
    form_config = result.scalar_one_or_none()
    if not form_config:
        raise HTTPException(status_code=404, detail=f"Form config '{form_id}' not found")

    if form_config.form_source != "anaplan":
        raise HTTPException(
            status_code=400,
            detail="This form is configured for Excel upload, not Anaplan direct read",
        )

    if not form_config.view_id:
        raise HTTPException(
            status_code=400,
            detail="Form config is missing view_id — set it via the form config API",
        )

    from app.services.anaplan_client import AnaplanClient

    try:
        token   = await _auth.get_token(tenant.client_id, tenant.credentials)
        anaplan = AnaplanClient(tenant.workspace_id, tenant.model_id, token)
        rows, hierarchy = anaplan.read_view_as_rows(form_config)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Anaplan read error: {exc}")

    if not rows:
        raise HTTPException(status_code=422, detail="No data returned from Anaplan view")

    config   = await build_client_config(db, form_config, tenant.client_id)
    filtered = apply_materiality_filter(rows, config)

    if not filtered.generate:
        raise HTTPException(
            status_code=422,
            detail="All rows were filtered by materiality — nothing to generate",
        )

    commentary, usage = await generate_commentary(config, filtered.generate, hierarchy)

    rows_with_commentary = [
        {**r, "commentary": commentary.get(r["member_id"], "")}
        for r in filtered.generate
    ]

    job_id = str(uuid.uuid4())
    await save_preview(tenant.client_id, job_id, rows_with_commentary, filtered.skipped, usage)

    return {
        "job_id":    job_id,
        "form_id":   form_id,
        "generated": len(filtered.generate),
        "skipped":   len(filtered.skipped),
        "status":    "pending_review",
    }
