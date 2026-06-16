"""Task dispatch with inline fallback when Celery worker is unavailable."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable

from app.core.config import get_settings

logger = logging.getLogger(__name__)


def dispatch_task(task: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Enqueue a Celery task, or run inline in a daemon thread for local dev."""
    settings = get_settings()
    if settings.celery_inline_fallback:
        logger.debug("Inline task execution: %s", getattr(task, "name", task))
        thread = threading.Thread(
            target=task,
            args=args,
            kwargs=kwargs,
            daemon=True,
            name=f"inline-{getattr(task, 'name', 'task')}",
        )
        thread.start()
        return
    task.delay(*args, **kwargs)
