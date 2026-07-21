"""FastAPI application entry."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from sqlalchemy import select

from app.api.v1.api import api_router
from app.api.v1.endpoints.platform import health_router
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.handlers import register_exception_handlers
from app.core.spa_static import SPAStaticFiles
from app.models.platform_setting import PlatformSetting
from app.services.tia.override_service import TiaOverrideService
from app.services.watch.ticker import get_watch_ticker
from app.services.watch.watch_webhook_runtime import (
    get_watch_webhook_runtime,
    resolve_from_db_row,
    resolve_from_env,
)

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSessionLocal() as session:
        await TiaOverrideService().load_all_into_registry(session)
    runtime = get_watch_webhook_runtime()
    try:
        async with AsyncSessionLocal() as session:
            row = (
                await session.execute(select(PlatformSetting).limit(1))
            ).scalar_one_or_none()
            runtime.apply(resolve_from_db_row(row))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "watch webhook runtime load from DB failed (%s); falling back to env",
            exc,
        )
        runtime.apply(resolve_from_env())
    ticker = get_watch_ticker()
    ticker.start()
    try:
        yield
    finally:
        await ticker.stop()


app = FastAPI(
    title=settings.app_name,
    description="NineHub A-share data management platform",
    version="0.1.0",
    lifespan=lifespan,
)

register_exception_handlers(app)

# API + WS must be registered BEFORE StaticFiles mounts.
app.include_router(health_router)
app.include_router(api_router, prefix="/api/v1")

static_path = Path(__file__).resolve().parent.parent / settings.static_dir
watch_path = static_path / "watch"
# Mount more specific /watch before catch-all /
if watch_path.is_dir():
    app.mount("/watch", SPAStaticFiles(directory=str(watch_path), html=True), name="watch")
if static_path.is_dir():
    app.mount("/", SPAStaticFiles(directory=str(static_path), html=True), name="static")
