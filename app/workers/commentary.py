import logging

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.services.generator import run_generation_and_preview, run_write
from app.services.webhook import fire_webhook

logger = logging.getLogger(__name__)


async def generate_commentary_job(ctx: dict, client_id: str, job_id: str) -> dict:
    logger.info("generate_commentary_job start client=%s job=%s", client_id, job_id)
    try:
        result = await run_generation_and_preview(client_id, job_id)
        await fire_webhook(client_id, "pending_review", job_id, result)
        return result
    except Exception as exc:
        logger.exception("generate_commentary_job failed client=%s job=%s", client_id, job_id)
        await fire_webhook(client_id, "error", job_id, {"error": str(exc)})
        raise


async def write_commentary_job(ctx: dict, client_id: str, job_id: str) -> dict:
    logger.info("write_commentary_job start client=%s job=%s", client_id, job_id)
    try:
        result = await run_write(client_id, job_id)
        await fire_webhook(client_id, "written", job_id, result)
        return result
    except Exception as exc:
        logger.exception("write_commentary_job failed client=%s job=%s", client_id, job_id)
        await fire_webhook(client_id, "error", job_id, {"error": str(exc)})
        raise


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    functions       = [generate_commentary_job, write_commentary_job]
    max_jobs        = 10
    job_timeout     = 600
    keep_result     = 3600
