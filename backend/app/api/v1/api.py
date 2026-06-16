"""V1 API router aggregation."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    catalog,
    platform,
    quality,
    sources,
    tasks,
    tia,
    workflows,
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
api_router.include_router(sources.router, prefix="/sources", tags=["sources"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(workflows.router, prefix="/workflows", tags=["workflows"])
api_router.include_router(tia.router, prefix="/tia", tags=["tia"])
api_router.include_router(quality.router, prefix="/quality", tags=["quality"])
api_router.include_router(platform.router, prefix="/platform", tags=["platform"])
