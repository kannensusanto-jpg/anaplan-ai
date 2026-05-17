import logging

logger = logging.getLogger(__name__)


async def audit_log(client_id: str, event: str, details: list) -> None:
    logger.info({"client_id": client_id, "event": event, "count": len(details)})
