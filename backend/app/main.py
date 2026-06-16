"""FastAPI application entry."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.v1.api import api_router
from app.api.v1.endpoints.platform import health_router
from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.core.handlers import register_exception_handlers
from app.services.tia.override_service import TiaOverrideService

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSessionLocal() as session:
        await TiaOverrideService().load_all_into_registry(session)
    yield


app = FastAPI(
    title=settings.app_name,
    description="NineHub A-share data management platform",
    version="0.1.0",
    lifespan=lifespan,
)

register_exception_handlers(app)

app.include_router(health_router)
app.include_router(api_router, prefix="/api/v1")

static_path = Path(__file__).resolve().parent.parent / settings.static_dir
if static_path.is_dir():
    app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")
