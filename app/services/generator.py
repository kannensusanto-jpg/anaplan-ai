import asyncio

import anthropic

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.models.usage import UsageRecord
from app.services.audit import audit_log
from app.services.auth import AnaplanAuthService
from app.services.config import ClientConfig
from app.services.materiality import apply_materiality_filter
from app.services.preview_store import delete_preview, load_preview, save_preview
from app.services.prompts import build_dataset_summary, build_system_prompt, build_user_prompt
from app.services.tenant_service import get_tenant

client       = anthropic.AsyncAnthropic()
auth_service = AnaplanAuthService(settings.ENCRYPTION_KEY.encode())


async def run_generation_and_preview(client_id: str, job_id: str) -> dict:
    from app.services.anaplan_client import AnaplanClient

    tenant    = await get_tenant(client_id)
    token     = await auth_service.get_token(client_id, tenant.credentials)
    anaplan   = AnaplanClient(tenant.workspace_id, tenant.model_id, token)

    config    = anaplan.read_config_module(tenant.config_module_id)
    raw_rows  = anaplan.read_module_data(tenant.target_module_id)
    hierarchy = anaplan.read_hierarchy(tenant.target_module_id)

    filtered = apply_materiality_filter(raw_rows, config)
    await audit_log(client_id, "filtered", [
        {"member": r["member_id"], "reason": reason}
        for r, reason in filtered.skipped
    ])

    commentary, usage = await generate_commentary(config, filtered.generate, hierarchy)

    rows_with_commentary = [
        {**r, "commentary": commentary.get(r["member_id"], "")}
        for r in filtered.generate
    ]

    await save_preview(client_id, job_id, rows_with_commentary, filtered.skipped, usage)

    return {
        "status":    "pending_review",
        "generated": len(filtered.generate),
        "skipped":   len(filtered.skipped),
        "client_id": client_id,
    }


async def run_write(client_id: str, job_id: str) -> dict:
    from app.services.anaplan_client import AnaplanClient

    preview = await load_preview(client_id)
    if not preview:
        raise ValueError("Preview not found or expired. Regenerate commentary first.")

    tenant  = await get_tenant(client_id)
    token   = await auth_service.get_token(client_id, tenant.credentials)
    anaplan = AnaplanClient(tenant.workspace_id, tenant.model_id, token)

    commentary = {r["member_id"]: r["commentary"] for r in preview["rows"]}

    await anaplan.write_commentary(
        import_action_id=tenant.import_action_id,
        file_id=tenant.commentary_file_id,
        commentary=commentary,
        rows=preview["rows"],
    )

    await delete_preview(client_id)

    usage = preview.get("usage", {})
    await _save_usage(
        client_id, job_id, "anaplan",
        len(preview["rows"]), len(preview["skipped"]), usage,
    )

    return {
        "status":    "written",
        "generated": len(preview["rows"]),
        "client_id": client_id,
    }


async def generate_commentary(
    config: ClientConfig,
    rows: list[dict],
    hierarchy: dict[str, list[str]],
    page_context: dict | None = None,
) -> tuple[dict[str, str], dict]:
    dataset_summary = build_dataset_summary(rows, page_context)
    system_prompt   = build_system_prompt(config, dataset_summary)
    results: dict[str, str] = {}
    totals = {
        "input_tokens": 0, "output_tokens": 0,
        "cache_read_tokens": 0, "cache_creation_tokens": 0,
    }

    leaf_rows   = [r for r in rows if r["member_id"] not in hierarchy]
    rollup_rows = [r for r in rows if r["member_id"] in hierarchy]

    leaf_outputs = await asyncio.gather(
        *[_call_claude(system_prompt, r, page_context=page_context) for r in leaf_rows]
    )
    for row, (text, usage) in zip(leaf_rows, leaf_outputs):
        results[row["member_id"]] = text
        _add_usage(totals, usage)

    for row in _order_rollups(rollup_rows, hierarchy):
        child_ids = hierarchy[row["member_id"]]
        row["child_commentary"] = "\n".join(
            f"- {cid}: {results[cid]}" for cid in child_ids if cid in results
        )
        text, usage = await _call_claude(system_prompt, row, is_rollup=True, page_context=page_context)
        results[row["member_id"]] = text
        _add_usage(totals, usage)

    return results, totals


async def _call_claude(
    system_prompt: str,
    row: dict,
    is_rollup: bool = False,
    page_context: dict | None = None,
) -> tuple[str, dict]:
    user_content = build_user_prompt(row, page_context)
    if is_rollup and row.get("child_commentary"):
        user_content += f"\n\nChild member commentary:\n{row['child_commentary']}"

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )

    usage = {
        "input_tokens":          response.usage.input_tokens,
        "output_tokens":         response.usage.output_tokens,
        "cache_read_tokens":     getattr(response.usage, "cache_read_input_tokens", 0),
        "cache_creation_tokens": getattr(response.usage, "cache_creation_input_tokens", 0),
    }
    return response.content[0].text.strip(), usage


def _add_usage(totals: dict, usage: dict) -> None:
    for key in totals:
        totals[key] += usage.get(key, 0)


def _order_rollups(rollup_rows: list[dict], hierarchy: dict) -> list[dict]:
    ordered, visited = [], set()

    def visit(member_id: str) -> None:
        if member_id in visited:
            return
        for child in hierarchy.get(member_id, []):
            visit(child)
        visited.add(member_id)
        match = next((r for r in rollup_rows if r["member_id"] == member_id), None)
        if match:
            ordered.append(match)

    for row in rollup_rows:
        visit(row["member_id"])
    return ordered


async def _save_usage(
    client_id: str, job_id: str, source: str,
    generated: int, skipped: int, usage: dict,
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(UsageRecord(
            client_id=client_id, job_id=job_id, source=source,
            rows_generated=generated, rows_skipped=skipped, **usage,
        ))
        await db.commit()
