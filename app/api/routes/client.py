from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant
from app.core.db import get_db
from app.models.tenant import Tenant
from app.models.usage import UsageRecord

router = APIRouter(prefix="/v1/client", tags=["client"])


@router.get("/me")
async def me(tenant: Tenant = Depends(get_current_tenant)):
    return {
        "client_id":    tenant.client_id,
        "company_name": tenant.company_name,
        "workspace_id": tenant.workspace_id,
        "model_id":     tenant.model_id,
        "has_webhook":  bool(tenant.webhook_url),
    }


@router.get("/usage")
async def usage_summary(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    result  = await db.execute(
        select(UsageRecord)
        .where(UsageRecord.client_id == tenant.client_id)
        .order_by(UsageRecord.created_at.desc())
        .limit(20)
    )
    records = result.scalars().all()

    total_input  = sum(r.input_tokens for r in records)
    total_output = sum(r.output_tokens for r in records)
    total_cache  = sum(r.cache_read_tokens for r in records)

    return {
        "recent_jobs": [
            {
                "job_id":         r.job_id,
                "source":         r.source,
                "rows_generated": r.rows_generated,
                "rows_skipped":   r.rows_skipped,
                "created_at":     r.created_at.isoformat(),
            }
            for r in records
        ],
        "totals": {
            "input_tokens":      total_input,
            "output_tokens":     total_output,
            "cache_read_tokens": total_cache,
        },
    }
