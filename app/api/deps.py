import hashlib

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.tenant import Tenant


async def get_current_tenant(
    x_api_key: str = Header(..., alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    key_hash = hashlib.sha256(x_api_key.encode()).hexdigest()
    tenant   = await Tenant.get_by_key_hash(db, key_hash)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return tenant


def require_admin(x_admin_key: str = Header(..., alias="X-Admin-Key")) -> None:
    import hashlib
    key_hash = hashlib.sha256(x_admin_key.encode()).hexdigest()
    if key_hash != settings.ADMIN_API_KEY_HASH:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin key")
