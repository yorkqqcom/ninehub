"""TIA runtime bootstrap — catalog registry + SyncHandler registration."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.database import SyncSessionLocal
from app.services.tia.override_service import TiaOverrideService


def bootstrap_tia_runtime(session: Session | None = None) -> int:
    """Load activated overrides into catalog registry and register handlers."""
    own_session = session is None
    if own_session:
        session = SyncSessionLocal()
    try:
        service = TiaOverrideService()
        activated = 0
        for override in service.list_all_sync(session):
            service.bootstrap_override(override)
            if override.is_activated:
                activated += 1
        return activated
    finally:
        if own_session and session is not None:
            session.close()


def register_default_handlers() -> None:
    """Register TIA handlers from DB (API lifespan + Celery worker)."""
    bootstrap_tia_runtime()
