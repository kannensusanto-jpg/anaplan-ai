from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func

from app.models.base import Base


class UsageRecord(Base):
    __tablename__ = "usage"

    id                    = Column(Integer, primary_key=True, autoincrement=True)
    client_id             = Column(String, ForeignKey("tenants.client_id"), nullable=False)
    job_id                = Column(String, nullable=False)
    source                = Column(String, nullable=False)
    rows_generated        = Column(Integer, default=0)
    rows_skipped          = Column(Integer, default=0)
    input_tokens          = Column(Integer, default=0)
    output_tokens         = Column(Integer, default=0)
    cache_read_tokens     = Column(Integer, default=0)
    cache_creation_tokens = Column(Integer, default=0)
    created_at            = Column(DateTime, default=func.now())
