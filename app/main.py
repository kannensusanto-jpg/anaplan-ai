import logging
from contextlib import asynccontextmanager

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from arq.connections import RedisSettings, create_pool
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import admin, client, jobs, upload
from app.core.config import settings
from app.core.db import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Running Alembic migrations...")
    cfg = AlembicConfig("alembic.ini")
    alembic_command.upgrade(cfg, "head")
    logger.info("Migrations complete")

    app.state.arq = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    logger.info("ARQ pool ready")

    yield

    await app.state.arq.aclose()
    await engine.dispose()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Anaplan AI Commentary",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(admin.router)
app.include_router(upload.router)
app.include_router(client.router)

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index():
    with open("app/templates/index.html") as f:
        return HTMLResponse(f.read())
