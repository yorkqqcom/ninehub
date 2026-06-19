"""Stdout progress for long-running backfill collects."""

from __future__ import annotations

import sys
from datetime import datetime
from typing import Callable

from app.sync.tia_collect.base import StrategyContext

DEFAULT_UPSERT_FLUSH_DAYS = 20
DEFAULT_UPSERT_FLUSH_CODES = 20

JobProgressFn = Callable[[int, str], None]


def log_backfill_progress(ctx: StrategyContext, message: str) -> None:
    """Emit timestamped line when batch_mode=backfill (visible in Celery / script logs)."""
    if ctx.sync_ctx.batch_mode != "backfill":
        return
    if ctx.extra.get("backfill_progress") is False:
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{ctx.data_type}] {message}"
    print(line, flush=True)
    file_obj = ctx.extra.get("backfill_log_file")
    if file_obj is not None:
        file_obj.write(line + "\n")
        file_obj.flush()


def should_log_interval(current: int, total: int, *, every: int = 25) -> bool:
    return current == 1 or current == total or current % every == 0


def upsert_flush_days(ctx: StrategyContext) -> int | None:
    if ctx.sync_ctx.batch_mode != "backfill":
        return None
    raw = ctx.extra.get("upsert_flush_days")
    if raw is None:
        return DEFAULT_UPSERT_FLUSH_DAYS
    days = int(raw)
    return days if days > 0 else None


def upsert_flush_codes(ctx: StrategyContext) -> int | None:
    if ctx.sync_ctx.batch_mode != "backfill":
        return None
    raw = ctx.extra.get("upsert_flush_codes")
    if raw is None:
        return DEFAULT_UPSERT_FLUSH_CODES
    codes = int(raw)
    return codes if codes > 0 else None
