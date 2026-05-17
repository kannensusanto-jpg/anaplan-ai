from sqlalchemy import Column, String, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base


class Tenant(Base):
    __tablename__ = "tenants"

    client_id          = Column(String, primary_key=True)
    company_name       = Column(String, nullable=False)
    workspace_id       = Column(String, nullable=False)
    model_id           = Column(String, nullable=False)
    config_module_id   = Column(String, nullable=False)
    target_module_id   = Column(String, nullable=False)
    import_action_id   = Column(String, nullable=False)
    commentary_file_id = Column(String, nullable=False)
    credentials        = Column(String, nullable=False)
    api_key_hash       = Column(String, nullable=False, unique=True)
    webhook_url        = Column(String, nullable=True)

    @classmethod
    async def get_by_key_hash(cls, key_hash: str, db: AsyncSession) -> "Tenant | None":
        result = await db.execute(select(cls).where(cls.api_key_hash == key_hash))
        return result.scalar_one_or_none()

    @classmethod
    async def get_by_client_id(cls, client_id: str, db: AsyncSession) -> "Tenant | None":
        result = await db.execute(select(cls).where(cls.client_id == client_id))
        return result.scalar_one_or_none()
