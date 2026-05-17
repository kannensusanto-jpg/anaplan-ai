import hashlib
import secrets

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_admin
from app.api.schemas.tenant import KeyRotated, TenantCreate, TenantCreated, TenantSummary
from app.core.config import settings
from app.core.db import get_db
from app.models.tenant import Tenant
from app.models.usage import UsageRecord

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)])

_fernet = Fernet(settings.ENCRYPTION_KEY.encode())


def _encrypt(value: str) -> str:
    return _fernet.encrypt(value.encode()).decode()


@router.post("/tenants", response_model=TenantCreated, status_code=201)
async def create_tenant(body: TenantCreate, db: AsyncSession = Depends(get_db)):
    existing = await Tenant.get_by_client_id(db, body.client_id)
    if existing:
        raise HTTPException(status_code=409, detail="client_id already registered")

    api_key  = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    credentials = _encrypt(f"{body.client_id}:{body.client_secret}")

    tenant = Tenant(
        client_id=body.client_id,
        company_name=body.company_name,
        workspace_id=body.workspace_id,
        model_id=body.model_id,
        config_module_id=body.config_module_id,
        target_module_id=body.target_module_id,
        import_action_id=body.import_action_id,
        commentary_file_id=body.commentary_file_id,
        credentials=credentials,
        api_key_hash=key_hash,
        webhook_url=body.webhook_url,
    )
    db.add(tenant)
    await db.commit()

    return TenantCreated(
        client_id=body.client_id,
        api_key=api_key,
        company_name=body.company_name,
    )


@router.get("/tenants", response_model=list[TenantSummary])
async def list_tenants(db: AsyncSession = Depends(get_db)):
    result  = await db.execute(select(Tenant))
    tenants = result.scalars().all()
    return [
        TenantSummary(
            client_id=t.client_id,
            company_name=t.company_name,
            workspace_id=t.workspace_id,
            model_id=t.model_id,
            has_webhook=bool(t.webhook_url),
        )
        for t in tenants
    ]


@router.delete("/tenants/{client_id}", status_code=204)
async def delete_tenant(client_id: str, db: AsyncSession = Depends(get_db)):
    tenant = await Tenant.get_by_client_id(db, client_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    await db.delete(tenant)
    await db.commit()


@router.post("/tenants/{client_id}/rotate-key", response_model=KeyRotated)
async def rotate_key(client_id: str, db: AsyncSession = Depends(get_db)):
    tenant = await Tenant.get_by_client_id(db, client_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    api_key          = secrets.token_urlsafe(32)
    tenant.api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    await db.commit()

    return KeyRotated(client_id=client_id, api_key=api_key)


@router.get("/tenants/{client_id}/usage")
async def tenant_usage(client_id: str, db: AsyncSession = Depends(get_db)):
    result  = await db.execute(
        select(UsageRecord)
        .where(UsageRecord.client_id == client_id)
        .order_by(UsageRecord.created_at.desc())
        .limit(50)
    )
    records = result.scalars().all()
    return [
        {
            "job_id":         r.job_id,
            "source":         r.source,
            "rows_generated": r.rows_generated,
            "rows_skipped":   r.rows_skipped,
            "input_tokens":   r.input_tokens,
            "output_tokens":  r.output_tokens,
            "cache_read":     r.cache_read_tokens,
            "created_at":     r.created_at.isoformat(),
        }
        for r in records
    ]
