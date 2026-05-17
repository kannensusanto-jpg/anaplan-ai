from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant, get_db
from app.api.schemas.form import ConfigProfileCreate, ConfigProfileOut, FormConfigIn, FormConfigOut
from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.form_config import ConfigProfile, FormConfig
from app.models.tenant import Tenant
from app.models.usage import UsageRecord
from app.services.auth import AnaplanAuthService
from app.services.config_profiles import get_profiles_for_client
from app.services.form_template import generate_form_config_template
from app.services.preview_store import delete_preview, load_preview

_auth = AnaplanAuthService(settings.ENCRYPTION_KEY.encode())

router = APIRouter(prefix="/v1", tags=["forms"])


# ── Config Profiles ────────────────────────────────────────────────────────────

@router.get("/profiles", response_model=list[ConfigProfileOut])
async def list_profiles(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    return await get_profiles_for_client(db, tenant.client_id)


@router.post("/profiles", response_model=ConfigProfileOut, status_code=201)
async def create_profile(
    body: ConfigProfileCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(ConfigProfile).where(
            ConfigProfile.profile_name == body.profile_name,
            ConfigProfile.client_id == tenant.client_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Profile name already exists for this client")

    profile = ConfigProfile(**body.model_dump(), client_id=tenant.client_id, is_global=False)
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    return profile


@router.delete("/profiles/{profile_name}", status_code=204)
async def delete_profile(
    profile_name: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ConfigProfile).where(
            ConfigProfile.profile_name == profile_name,
            ConfigProfile.client_id == tenant.client_id,
            ConfigProfile.is_global.is_(False),
        )
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Custom profile not found")
    await db.delete(profile)
    await db.commit()


# ── Form Configs ───────────────────────────────────────────────────────────────

@router.get("/forms/config-template")
async def download_form_config_template():
    data = generate_form_config_template()
    return StreamingResponse(
        BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=form_config_template.xlsx"},
    )


@router.get("/forms", response_model=list[FormConfigOut])
async def list_forms(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormConfig)
        .where(FormConfig.client_id == tenant.client_id)
        .order_by(FormConfig.form_name)
    )
    return result.scalars().all()


@router.post("/forms", response_model=FormConfigOut, status_code=201)
async def upsert_form(
    body: FormConfigIn,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormConfig).where(
            FormConfig.client_id == tenant.client_id,
            FormConfig.form_id == body.form_id,
        )
    )
    form = result.scalar_one_or_none()

    data = body.model_dump()
    if form:
        for k, v in data.items():
            setattr(form, k, v)
    else:
        form = FormConfig(**data, client_id=tenant.client_id)
        db.add(form)

    await db.commit()
    await db.refresh(form)
    return form


@router.get("/forms/{form_id}", response_model=FormConfigOut)
async def get_form(
    form_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormConfig).where(
            FormConfig.client_id == tenant.client_id,
            FormConfig.form_id == form_id,
        )
    )
    form = result.scalar_one_or_none()
    if not form:
        raise HTTPException(status_code=404, detail="Form config not found")
    return form


@router.delete("/forms/{form_id}", status_code=204)
async def delete_form(
    form_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FormConfig).where(
            FormConfig.client_id == tenant.client_id,
            FormConfig.form_id == form_id,
        )
    )
    form = result.scalar_one_or_none()
    if not form:
        raise HTTPException(status_code=404, detail="Form config not found")
    await db.delete(form)
    await db.commit()


# ── Approve / write-back ───────────────────────────────────────────────────────

@router.post("/forms/approve")
async def approve_form_preview(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Write the pending preview commentary back to Anaplan using the form's
    import_action_id.  The form_id must be stored in the preview (set
    automatically when generating via /anaplan/generate-form or
    /upload/grid-generate).
    """
    preview = await load_preview(tenant.client_id)
    if not preview:
        raise HTTPException(status_code=404, detail="No pending preview — generate first")

    form_id = preview.get("form_id")
    if not form_id:
        raise HTTPException(
            status_code=400,
            detail="Preview was not generated from a form config — use /v1/jobs/approve instead",
        )

    result = await db.execute(
        select(FormConfig).where(
            FormConfig.client_id == tenant.client_id,
            FormConfig.form_id == form_id,
        )
    )
    form_config = result.scalar_one_or_none()
    if not form_config:
        raise HTTPException(status_code=404, detail=f"Form config '{form_id}' not found")

    if not form_config.import_action_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Form config is missing import_action_id. "
                "Set it via the form config API, or use Export to Excel instead."
            ),
        )

    from app.services.anaplan_client import AnaplanClient

    commentary = {r["member_id"]: r["commentary"] for r in preview["rows"]}

    try:
        token   = await _auth.get_token(tenant.client_id, tenant.credentials)
        anaplan = AnaplanClient(tenant.workspace_id, tenant.model_id, token)
        # In Anaplan, the source file for an import usually shares its ID with the
        # import action. Use import_action_id as the file_id by default.
        await anaplan.write_commentary(
            import_action_id=form_config.import_action_id,
            file_id=form_config.import_action_id,
            commentary=commentary,
            rows=preview["rows"],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Anaplan write error: {exc}")

    await delete_preview(tenant.client_id)

    # Record usage
    usage = preview.get("usage", {})
    job_id = preview.get("job_id", "unknown")
    async with AsyncSessionLocal() as usage_db:
        usage_db.add(UsageRecord(
            client_id=tenant.client_id,
            job_id=job_id,
            source=f"form:{form_id}",
            rows_generated=len(preview["rows"]),
            rows_skipped=len(preview.get("skipped", [])),
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_tokens=usage.get("cache_read_tokens", 0),
            cache_creation_tokens=usage.get("cache_creation_tokens", 0),
        ))
        await usage_db.commit()

    return {
        "status":    "written",
        "form_id":   form_id,
        "generated": len(preview["rows"]),
    }
