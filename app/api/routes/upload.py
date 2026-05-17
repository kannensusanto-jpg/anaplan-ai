import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant, get_db
from app.models.form_config import FormConfig
from app.models.tenant import Tenant
from app.services.config_profiles import build_client_config
from app.services.excel_parser import parse_excel
from app.services.excel_template import generate_template
from app.services.excel_writer import build_preview_excel, write_commentary_to_excel
from app.services.generator import generate_commentary
from app.services.grid_parser import parse_grid
from app.services.materiality import apply_materiality_filter
from app.services.preview_store import save_preview

router = APIRouter(prefix="/v1/upload", tags=["upload"])

EXCEL_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/template")
async def download_template():
    excel_bytes = generate_template()
    return StreamingResponse(
        iter([excel_bytes]),
        media_type=EXCEL_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=commentary_template.xlsx"},
    )


@router.post("/generate")
async def upload_and_generate(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_current_tenant),
):
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="File must be an .xlsx spreadsheet")

    file_bytes = await file.read()
    try:
        config, rows, hierarchy = parse_excel(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

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
        "generated": len(filtered.generate),
        "skipped":   len(filtered.skipped),
        "status":    "pending_review",
    }


@router.get("/preview/export")
async def export_upload_preview(tenant: Tenant = Depends(get_current_tenant)):
    from app.services.preview_store import load_preview
    preview = await load_preview(tenant.client_id)
    if not preview:
        raise HTTPException(status_code=404, detail="No pending preview")
    excel_bytes = build_preview_excel(preview)
    return StreamingResponse(
        iter([excel_bytes]),
        media_type=EXCEL_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=commentary_preview.xlsx"},
    )


@router.post("/grid-generate")
async def upload_grid_and_generate(
    file: UploadFile = File(...),
    form_id: str = Form(...),
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload an Anaplan-style grid Excel file and generate AI commentary.
    Requires a saved form config (form_id) to know dimension mappings.
    """
    if not file.filename or not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="File must be an .xlsx spreadsheet")

    result = await db.execute(
        select(FormConfig).where(
            FormConfig.client_id == tenant.client_id,
            FormConfig.form_id == form_id,
        )
    )
    form_config = result.scalar_one_or_none()
    if not form_config:
        raise HTTPException(status_code=404, detail=f"Form config '{form_id}' not found")

    file_bytes = await file.read()
    try:
        rows, hierarchy = parse_grid(file_bytes, form_config)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Grid parse error: {exc}")

    if not rows:
        raise HTTPException(status_code=422, detail="No data rows found in the grid")

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


@router.post("/approve-download")
async def approve_and_download(
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_current_tenant),
):
    """Return original file with AI Commentary column filled in."""
    from app.services.preview_store import delete_preview, load_preview

    preview = await load_preview(tenant.client_id)
    if not preview:
        raise HTTPException(status_code=404, detail="No pending preview — run /upload/generate first")

    original_bytes = await file.read()
    commentary     = {r["member_id"]: r["commentary"] for r in preview["rows"]}
    skipped        = [(s, s["reason"]) for s in preview["skipped"]]

    result_bytes = write_commentary_to_excel(original_bytes, commentary, skipped)
    await delete_preview(tenant.client_id)

    return StreamingResponse(
        iter([result_bytes]),
        media_type=EXCEL_MEDIA_TYPE,
        headers={"Content-Disposition": "attachment; filename=commentary_output.xlsx"},
    )
