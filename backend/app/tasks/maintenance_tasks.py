"""Maintenance Celery tasks."""

import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.database import SyncSessionLocal
from app.models.watch import WatchAlertEvent
from app.tasks.celery_app import celery_app


@celery_app.task(name="ninehub.cleanup_export_files")
def cleanup_export_files_task(max_age_days: int | None = None) -> dict:
    settings = get_settings()
    days = int(max_age_days if max_age_days is not None else settings.export_retention_days)
    export_root = Path(settings.static_dir) / settings.export_dir
    if not export_root.is_dir():
        return {"deleted": 0, "message": "export dir missing"}
    cutoff = time.time() - days * 86400
    deleted = 0
    patterns = ("export_*", "browser_*", "backtest_*")
    seen: set[Path] = set()
    for pattern in patterns:
        for path in export_root.glob(pattern):
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            if path.stat().st_mtime < cutoff:
                path.unlink(missing_ok=True)
                deleted += 1
    return {"deleted": deleted, "message": f"Removed {deleted} expired exports"}


@celery_app.task(name="ninehub.cleanup_watch_alerts")
def cleanup_watch_alerts_task(max_age_days: int | None = None, batch_size: int = 5000) -> dict:
    settings = get_settings()
    days = int(max_age_days if max_age_days is not None else settings.watch_alert_retention_days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0
    session = SyncSessionLocal()
    try:
        while True:
            ids = (
                session.execute(
                    select(WatchAlertEvent.id)
                    .where(WatchAlertEvent.created_at < cutoff)
                    .order_by(WatchAlertEvent.id.asc())
                    .limit(batch_size)
                )
                .scalars()
                .all()
            )
            if not ids:
                break
            session.execute(delete(WatchAlertEvent).where(WatchAlertEvent.id.in_(ids)))
            session.commit()
            deleted += len(ids)
        return {"deleted": deleted, "message": f"Removed {deleted} expired watch alerts"}
    finally:
        session.close()
