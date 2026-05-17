import uuid

from arq.connections import ArqRedis, create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_tenant
from app.core.config import settings
from app.models.tenant import Tenant
from app.services.excel_writer import build_preview_excel
from app.services.preview_store import delete_preview, load_preview

router = APIRouter(prefix="/v1/jobs", tags=["jobs"])


async def _get_arq(request: Request) -> ArqRedis:
    return request.app.state.arq


@router.post("/generate")
async def trigger_generate(
    tenant: Tenant = Depends(get_current_tenant),
    arq: ArqRedis = Depends(_get_arq),
):
    job_id = str(uuid.uuid4())
    await arq.enqueue_job(
        "generate_commentary_job",
        tenant.client_id,
        job_id,
        _job_id=f"gen:{tenant.client_id}:{job_id}",
    )
    return {"job_id": job_id, "status": "queued"}


@router.get("/status/{job_id}")
async def job_status(
    job_id: str,
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
):
    arq: ArqRedis = request.app.state.arq
    job = await arq.job_from_id(f"gen:{tenant.client_id}:{job_id}")
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    info = await job.info()
    return {
        "job_id": job_id,
        "status": info.status.value if info else "unknown",
        "result": info.result if info and info.success else None,
    }


@router.get("/preview")
async def get_preview(tenant: Tenant = Depends(get_current_tenant)):
    preview = await load_preview(tenant.client_id)
    if not preview:
        raise HTTPException(status_code=404, detail="No pending preview — run /generate first")
    return preview


@router.post("/approve")
async def approve_preview(
    tenant: Tenant = Depends(get_current_tenant),
    arq: ArqRedis = Depends(_get_arq),
):
    preview = await load_preview(tenant.client_id)
    if not preview:
        raise HTTPException(status_code=404, detail="No pending preview")
    job_id = str(uuid.uuid4())
    await arq.enqueue_job(
        "write_commentary_job",
        tenant.client_id,
        job_id,
        _job_id=f"write:{tenant.client_id}:{job_id}",
    )
    return {"job_id": job_id, "status": "queued"}


@router.post("/reject")
async def reject_preview(tenant: Tenant = Depends(get_current_tenant)):
    await delete_preview(tenant.client_id)
    return {"status": "discarded"}


@router.get("/preview/export")
async def export_preview_excel(tenant: Tenant = Depends(get_current_tenant)):
    preview = await load_preview(tenant.client_id)
    if not preview:
        raise HTTPException(status_code=404, detail="No pending preview")
    excel_bytes = build_preview_excel(preview)
    return StreamingResponse(
        iter([excel_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=commentary_preview.xlsx"},
    )
