"""Tests for Celery inline fallback dispatch."""

import time
from unittest.mock import patch

from app.core.config import get_settings
from app.tasks.dispatch import dispatch_task
from app.tasks.tia_tasks import run_tia_scan_task


def test_inline_dispatch_runs_in_thread(monkeypatch) -> None:
    monkeypatch.setenv("CELERY_INLINE_FALLBACK", "true")
    get_settings.cache_clear()

    called: list[int] = []

    def fake_task(job_id: int) -> None:
        called.append(job_id)

    dispatch_task(fake_task, 99)
    time.sleep(0.15)
    assert called == [99]
    get_settings.cache_clear()


def test_celery_dispatch_calls_delay(monkeypatch) -> None:
    monkeypatch.setenv("CELERY_INLINE_FALLBACK", "false")
    get_settings.cache_clear()

    with patch.object(run_tia_scan_task, "delay") as mock_delay:
        dispatch_task(run_tia_scan_task, 42)
        mock_delay.assert_called_once_with(42)

    get_settings.cache_clear()
