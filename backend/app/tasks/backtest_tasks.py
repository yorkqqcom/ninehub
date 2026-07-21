"""Celery task for research backtests."""

from __future__ import annotations

import asyncio
import concurrent.futures
from collections.abc import Coroutine
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.services.platform.job_service import PlatformJobService
from app.services.research.runner import BacktestRunner
from app.tasks.celery_app import celery_app

T = TypeVar("T")


def _run_coro(coro: Coroutine[Any, Any, T]) -> T:
    """Run async work from sync Celery context; safe if a loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def _with_isolated_session(job_id: int, *, fail_message: str | None = None) -> dict:
    """Use a fresh engine bound to the current loop (avoids cross-loop pool reuse)."""
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    jobs = PlatformJobService()
    try:
        async with session_factory() as session:
            if fail_message is not None:
                await jobs.update(
                    session,
                    job_id,
                    status="failed",
                    progress=100,
                    message="backtest failed",
                    error=fail_message,
                )
                await session.commit()
                return {"job_id": job_id, "status": "failed", "error": fail_message}
            runner = BacktestRunner()
            return await runner.run_job(session, job_id)
    finally:
        await engine.dispose()


@celery_app.task(name="ninehub.run_backtest")
def run_backtest_task(job_id: int) -> dict:
    try:
        return _run_coro(_with_isolated_session(job_id))
    except Exception as exc:
        message = exc.message if isinstance(exc, AppException) else str(exc)
        try:
            _run_coro(_with_isolated_session(job_id, fail_message=message))
        except Exception:
            pass
        return {"job_id": job_id, "status": "failed", "error": message}
