"""Maintenance Celery tasks."""

import os
import time
from pathlib import Path

from app.core.config import get_settings
from app.tasks.celery_app import celery_app


@celery_app.task(name="ninehub.cleanup_export_files")
def cleanup_export_files_task(max_age_days: int = 30) -> dict:
    settings = get_settings()
    export_root = Path(settings.export_dir)
    if not export_root.is_dir():
        return {"deleted": 0, "message": "export dir missing"}
    cutoff = time.time() - max_age_days * 86400
    deleted = 0
    for path in export_root.glob("export_*.csv"):
        if path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
            deleted += 1
    return {"deleted": deleted, "message": f"Removed {deleted} expired exports"}
