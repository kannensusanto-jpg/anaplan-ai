import json
from datetime import datetime, timezone

from app.core.redis_client import get_redis

PREVIEW_TTL = 86_400  # 24 hours


def _key(client_id: str) -> str:
    return f"preview:{client_id}"


async def save_preview(
    client_id: str,
    job_id: str,
    rows: list[dict],
    skipped: list[tuple[dict, str]],
    usage: dict,
) -> None:
    payload = {
        "job_id":       job_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": [
            {
                "member_id":        r["member_id"],
                "account":          r["account"],
                "cost_center":      r["cost_center"],
                "time_period":      r["time_period"],
                "actual":           r["actual"],
                "budget":           r["budget"],
                "variance_dollars": r["variance_dollars"],
                "variance_pct":     r["variance_pct"],
                "commentary":       r.get("commentary", ""),
                "is_rollup":        r.get("is_rollup", False),
            }
            for r in rows
        ],
        "skipped": [
            {
                "account":          row["account"],
                "cost_center":      row["cost_center"],
                "time_period":      row["time_period"],
                "variance_dollars": row["variance_dollars"],
                "reason":           reason,
            }
            for row, reason in skipped
        ],
        "usage": usage,
    }
    redis = get_redis()
    await redis.set(_key(client_id), json.dumps(payload), ex=PREVIEW_TTL)


async def load_preview(client_id: str) -> dict | None:
    raw = await get_redis().get(_key(client_id))
    return json.loads(raw) if raw else None


async def delete_preview(client_id: str) -> None:
    await get_redis().delete(_key(client_id))
