import hashlib
import os
import secrets

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATABASE_URL",        "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("REDIS_URL",           "redis://localhost:6379/1")
os.environ.setdefault("ANTHROPIC_API_KEY",   "test-key")
os.environ.setdefault("ENCRYPTION_KEY",      "Aq3V8zLmN2Pf6YtRwXkDsJhUiObEcGvMnQl5Ty9Fa0=")
os.environ.setdefault("ADMIN_API_KEY_HASH",  hashlib.sha256(b"test-admin-key").hexdigest())

from app.core.db import get_db
from app.main import app
from app.models.base import Base

TEST_ENGINE = create_async_engine("sqlite+aiosqlite:///./test.db", echo=False)
TestSession  = sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def create_tables():
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with TEST_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db():
    async with TestSession() as session:
        yield session


@pytest_asyncio.fixture
async def client(db):
    async def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    # Stub out ARQ pool so startup doesn't need real Redis
    class FakeArq:
        async def enqueue_job(self, *a, **kw): pass
        async def aclose(self): pass

    from unittest.mock import AsyncMock, MagicMock, patch
    with patch("app.main.create_pool", return_value=FakeArq()), \
         patch("alembic.command.upgrade"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def admin_headers():
    return {"X-Admin-Key": "test-admin-key"}


@pytest_asyncio.fixture
async def tenant_and_key(client, admin_headers):
    resp = await client.post("/v1/admin/tenants", headers=admin_headers, json={
        "company_name":       "Acme Corp",
        "client_id":          "acme-test",
        "workspace_id":       "ws1",
        "model_id":           "m1",
        "config_module_id":   "cfg1",
        "target_module_id":   "tgt1",
        "import_action_id":   "imp1",
        "commentary_file_id": "file1",
        "client_secret":      "secret",
    })
    data = resp.json()
    return data["client_id"], data["api_key"]
