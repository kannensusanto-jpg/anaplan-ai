import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


async def fire_webhook(webhook_url: str, payload: dict) -> None:
    if not webhook_url:
        return
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(webhook_url, json=payload)
            resp.raise_for_status()
    except Exception as exc:
        logger.warning({"event": "webhook_failed", "url": webhook_url, "error": str(exc)})


def build_payload(client_id: str, job_id: str, result: dict | None, error: str | None) -> dict:
    return {
        "client_id":    client_id,
        "job_id":       job_id,
        "status":       "complete" if error is None else "failed",
        "generated":    result.get("generated") if result else None,
        "skipped":      result.get("skipped") if result else None,
        "error":        error,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
