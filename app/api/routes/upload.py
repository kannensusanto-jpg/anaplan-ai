import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_tenant
from app.models.tenant import Tenant
from app.services.excel_parser import parse_excel
from app.services.excel_template import generate_template
from app.services.excel_writer import build_preview_excel, write_commentary_to_excel
from app.services.generator import generate_commentary
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
