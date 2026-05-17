from app.core.db import AsyncSessionLocal
from app.models.tenant import Tenant


async def get_tenant(client_id: str) -> Tenant:
    async with AsyncSessionLocal() as db:
        tenant = await Tenant.get_by_client_id(client_id, db)
        if not tenant:
            raise ValueError(f"Tenant not found: {client_id}")
        return tenant
