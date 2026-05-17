from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant
from app.api.schemas.form import ConfigProfileCreate, ConfigProfileOut, FormConfigIn, FormConfigOut
from app.core.db import get_db
from app.models.form_config import ConfigProfile, FormConfig
from app.models.tenant import Tenant
from app.services.config_profiles import get_profiles_for_client
from app.services.form_template import generate_form_config_template

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
