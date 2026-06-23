#!/usr/bin/env python3
"""Chunked historical backfill from platform sync_start_date (e.g. 2020-01-01).

Workflow `batch_mode=backfill` pulls the full date span in one run and hits the
200 API-call budget for trade_date / ts_code / period strategies. This script
splits work into chunks that fit the budget and can resume from existing data.

Usage:
  python scripts/run_backfill_history.py --list
  python scripts/run_backfill_history.py --data-type tushare_daily
  python scripts/run_backfill_history.py --tier 2
  python scripts/run_backfill_history.py --all --dry-run
  python scripts/run_backfill_history.py --data-type tushare_stk_holdertrade --from-chunk 21

``--truncate`` empties each target table before backfill (full reload from sync_start_date).
Keep tier-0 tables (especially stock_basic) when only re-running tier 1+.

Progress is written to stdout (line-buffered) and logs/backfill_history.log by default.
Each chunk logs START before API calls and DONE with rows/ETA after commit.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import IO, TextIO, Callable

JobProgressFn = Callable[[int, str], None]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Line-buffered stdout so long chunks show progress immediately in terminals / CI.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import sync_engine

from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.platform_setting import PlatformSetting
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal  # noqa: F401
from app.models.user import User  # noqa: F401
from app.services.platform.service import PlatformService
from app.services.tia.credentials import require_tushare_token, resolve_tushare_collect_credentials
from app.services.tia.override_service import TiaOverrideService
from app.services.tushare.source_quota import resolve_max_calls_per_minute
from app.services.workflow.collect_batch import (
    DAILY_BATCH_MODE_OVERRIDES,
    DAILY_MAX_API_CALLS,
    DAILY_ROTATION_CODES,
    resolve_rotation_codes,
    resolve_workflow_collect_config,
    resolve_workflow_sync_profile,
)
from app.sync.executor import SyncExecutor
from app.sync.handlers import SyncContext
from app.sync.tia_collect.period import PERIOD_MARKET_APIS, _periods_in_range
from app.sync.tia_collect.stock_codes import resolve_stock_codes
from app.sync.tia_collect.trade_date import _trading_days_in_range

API_BUDGET = DAILY_MAX_API_CALLS
DEFAULT_CHUNK_DAYS = 100
_CHUNK_DAYS = DEFAULT_CHUNK_DAYS

# Conservative upsert: smaller flushes/batches, SQLAlchemy path, sync commit per batch.
CONSERVATIVE_UPSERT_EXTRA = {
    "upsert_flush_days": 5,
    "upsert_flush_codes": 5,
    "upsert_batch_size": 200,
    "fast_upsert": False,
    "use_execute_values": False,
    "upsert_commit_per_batch": True,
    "upsert_batch_progress": True,
}
FAST_UPSERT_EXTRA = {
    "upsert_flush_days": 20,
    "upsert_flush_codes": 20,
    "upsert_batch_size": 1000,
    "fast_upsert": True,
    "use_execute_values": True,
    "upsert_commit_per_batch": False,
    "upsert_batch_progress": True,
}
_USE_FAST_UPSERT = False


def _upsert_extra() -> dict:
    return FAST_UPSERT_EXTRA if _USE_FAST_UPSERT else CONSERVATIVE_UPSERT_EXTRA


def _collect_run_failed(msg: str) -> bool:
    text = msg or ""
    lower = text.lower()
    return (
        "failed" in lower
        or "retryerror" in lower
        or "exceeds limit" in lower
        or "未配置" in text
    )


def _stock_code_total(session: Session) -> int:
    codes, _ = resolve_stock_codes(
        session, {"stock_codes_table": "tushare_stock_basic"}, max_codes=10_000
    )
    return len(codes)


def _schema_capped(schema: dict, *, max_codes_per_run: int) -> dict:
    schema_run = dict(schema)
    collect = dict(schema_run.get("collect") or {})
    collect["max_codes_per_run"] = max_codes_per_run
    collect["max_api_calls_per_run"] = API_BUDGET
    schema_run["collect"] = collect
    return schema_run


def _finish_rotation_chunk(*, calls: int, msg: str) -> None:
    """Raise on API/strategy failure; caller breaks loop only on natural zero-call end."""
    if _collect_run_failed(msg):
        raise RuntimeError(msg or "collect failed")
    if calls == 0:
        raise RuntimeError(msg or "collect returned 0 api calls")


def _chunk_start_offset(from_chunk: int, per_chunk: int) -> int:
    """Map 1-based chunk index to unit offset (stock codes or day index)."""
    return max(0, (max(1, from_chunk) - 1) * per_chunk)


def _handle_chunk_failure(data_type: str, chunks_done: int, exc: RuntimeError) -> tuple[int, bool]:
    log = _logger()
    log.log(f"[{data_type}] chunk {chunks_done} 失败，已保留前序进度: {exc}")
    return chunks_done, False


def _chunk_budget() -> int:
    return min(_CHUNK_DAYS, API_BUDGET)

# tier: lower runs first; within tier order matters (stock_basic before daily)
BACKFILL_PLAN: list[tuple[int, str, str]] = [
    (0, "tushare_trade_cal", "trade_cal"),
    (0, "tushare_stock_basic", "stock_basic"),
    (0, "tushare_index_classify", "index_classify"),
    (0, "tushare_index_member_all", "index_member_all"),
    (1, "tushare_daily", "daily"),
    (1, "tushare_daily_basic", "daily_basic"),
    (1, "tushare_adj_factor", "adj_factor"),
    (1, "tushare_stk_limit", "stk_limit"),
    (1, "tushare_margin", "margin"),
    (1, "tushare_margin_secs", "margin_secs"),
    (1, "tushare_block_trade", "block_trade"),
    (1, "tushare_top_list", "top_list"),
    (2, "tushare_weekly", "weekly"),
    (2, "tushare_bse_mapping", "bse_mapping"),
    (2, "tushare_new_share", "new_share"),
    (3, "tushare_stock_company", "stock_company"),
    (3, "tushare_income", "income"),
    (3, "tushare_balancesheet", "balancesheet"),
    (3, "tushare_cashflow", "cashflow"),
    (3, "tushare_express", "express"),
    (3, "tushare_forecast", "forecast"),
    (3, "tushare_fina_indicator", "fina_indicator"),
    (3, "tushare_fina_mainbz", "fina_mainbz"),
    (3, "tushare_disclosure_date", "disclosure_date"),
    (4, "tushare_top10_holders", "top10_holders"),
    (4, "tushare_top10_floatholders", "top10_floatholders"),
    (4, "tushare_stk_holdernumber", "stk_holdernumber"),
    (4, "tushare_stk_managers", "stk_managers"),
    (4, "tushare_stk_rewards", "stk_rewards"),
    (4, "tushare_stk_holdertrade", "stk_holdertrade"),
    (4, "tushare_pledge_stat", "pledge_stat"),
    (4, "tushare_pledge_detail", "pledge_detail"),
    (4, "tushare_dividend", "dividend"),
    (4, "tushare_repurchase", "repurchase"),
    (4, "tushare_hk_hold", "hk_hold"),
    (4, "tushare_index_member", "index_member"),
    (4, "tushare_index_weight", "index_weight"),
]

DATE_COLUMNS = ("trade_date", "cal_date", "ann_date", "end_date")
RECENT_TAIL_DAYS = 21  # separate daily-batch tail from historical backfill gap
DEFAULT_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


class BackfillLogger:
    """Timestamped progress lines to stdout and optional log file."""

    def __init__(
        self,
        log_path: Path | None = None,
        *,
        job_updater: JobProgressFn | None = None,
        total_units: int = 1,
    ) -> None:
        self._t0 = time.perf_counter()
        self._file: TextIO | None = None
        self._job_updater = job_updater
        self._total_units = max(1, total_units)
        self._units_done = 0
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = log_path.open("a", encoding="utf-8")
            self.log(f"===== session start {datetime.now().isoformat(timespec='seconds')} =====")

    def close(self) -> None:
        if self._file is not None:
            self.log(f"===== session end elapsed={self._elapsed():.1f}s =====")
            self._file.close()
            self._file = None

    def log_file_handle(self) -> IO[str] | None:
        return self._file

    def _elapsed(self) -> float:
        return time.perf_counter() - self._t0

    def log(self, message: str) -> None:
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {message}"
        print(line, flush=True)
        if self._file is not None:
            self._file.write(line + "\n")
            self._file.flush()

    def table_begin(self, index: int, total: int, data_type: str, plan: "ChunkPlan") -> None:
        self.log(
            f">>> [{index}/{total}] {data_type} mode={plan.mode} "
            f"chunks={plan.chunks} | {plan.note}"
        )

    def table_end(self, data_type: str, chunks_done: int, *, ok: bool = True) -> None:
        status = "OK" if ok else "FAIL"
        self.log(f"<<< {data_type} {status} chunks_done={chunks_done} elapsed={self._elapsed():.1f}s")

    def chunk_begin(
        self,
        data_type: str,
        chunk_no: int,
        total_chunks: int,
        *,
        label: str,
        detail: str,
    ) -> float:
        pct = int(100 * chunk_no / total_chunks) if total_chunks else 0
        self.log(f"  [{data_type}] {label} {chunk_no}/{total_chunks} ({pct}%) START {detail}")
        return time.perf_counter()

    def chunk_end(
        self,
        data_type: str,
        chunk_no: int,
        total_chunks: int,
        *,
        started: float,
        rows: int,
        calls: int,
        extra: str = "",
    ) -> None:
        elapsed = time.perf_counter() - started
        eta_chunks = total_chunks - chunk_no
        eta_s = eta_chunks * elapsed if chunk_no > 0 else 0
        eta_txt = f" ETA~{eta_s / 60:.1f}min" if eta_chunks > 0 and elapsed > 0 else ""
        self.log(
            f"  [{data_type}] chunk {chunk_no}/{total_chunks} DONE "
            f"{elapsed:.1f}s rows={rows} calls={calls}{eta_txt} {extra}".rstrip()
        )
        self._units_done += 1
        if self._job_updater is not None:
            pct = min(99, int(100 * self._units_done / self._total_units))
            self._job_updater(pct, f"{data_type} chunk {chunk_no}/{total_chunks}")


_LOGGER: BackfillLogger | None = None


def _logger() -> BackfillLogger:
    global _LOGGER
    if _LOGGER is None:
        _LOGGER = BackfillLogger()
    return _LOGGER


def _next_trading_day(d: date) -> date:
    from app.services.trading_calendar.service import CN_HOLIDAYS

    cursor = d + timedelta(days=1)
    while cursor.weekday() >= 5 or cursor in CN_HOLIDAYS:
        cursor += timedelta(days=1)
    return cursor


def _as_date(val: object) -> date | None:
    if val is None:
        return None
    if hasattr(val, "date"):
        return val.date()  # type: ignore[union-attr]
    if isinstance(val, str) and len(val) >= 10:
        return date.fromisoformat(val[:10])
    if isinstance(val, date):
        return val
    return None


def _primary_date_column(session: Session, table_name: str) -> str | None:
    cols = _table_date_columns(session, table_name)
    return cols[0] if cols else None


def _trade_date_backfill_span(
    session: Session,
    table_name: str,
    global_start: date,
    end: date,
) -> tuple[date, date, str]:
    """Forward-fill historical segment, excluding recent daily-batch tail."""
    col = _primary_date_column(session, table_name)
    if not col:
        return global_start, end, "no date column"

    recent_cutoff = end - timedelta(days=RECENT_TAIL_DAYS)
    recent_min = _as_date(
        session.execute(
            text(f'SELECT MIN("{col}") FROM "{table_name}" WHERE "{col}" >= :cut'),
            {"cut": recent_cutoff},
        ).scalar()
    )
    hist_end = (_as_date(recent_min) - timedelta(days=1)) if recent_min else end

    hist_max = _as_date(
        session.execute(
            text(
                f'SELECT MAX("{col}") FROM "{table_name}" '
                f'WHERE "{col}" >= :gs AND "{col}" <= :he'
            ),
            {"gs": global_start, "he": hist_end},
        ).scalar()
    )
    span_start = _next_trading_day(hist_max) if hist_max else global_start

    if span_start > hist_end:
        tail = f", recent tail from {recent_min}" if recent_min else ""
        return span_start, hist_end, f"complete through {hist_end}{tail}"

    note = f"forward {span_start}..{hist_end}"
    if recent_min:
        note += f" (recent tail from {recent_min})"
    return span_start, hist_end, note


@dataclass
class ChunkPlan:
    data_type: str
    api_name: str
    mode: str
    chunks: int
    note: str


def _db_session() -> Session:
    return Session(sync_engine)


def _resolve_source(session: Session) -> tuple[str, str, dict, int | None]:
    creds = resolve_tushare_collect_credentials(session)
    return (
        str(creds.get("provider") or "tushare"),
        str(creds.get("token") or ""),
        dict(creds.get("source_config") or {}),
        creds.get("source_id"),
    )


def _global_start(session: Session, data_type: str) -> date:
    row = session.execute(select(PlatformSetting).limit(1)).scalar_one_or_none()
    if row:
        start_str = PlatformService().resolve_sync_start_date_sync(session, data_type)
    else:
        from app.core.config import get_settings

        start_str = get_settings().sync_start_date
    return date.fromisoformat(start_str)


def _table_date_columns(session: Session, table_name: str) -> list[str]:
    rows = session.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = :t
              AND column_name = ANY(:cols)
            """
        ),
        {"t": table_name, "cols": list(DATE_COLUMNS)},
    ).fetchall()
    return [r[0] for r in rows]


def _table_min_date(session: Session, table_name: str) -> date | None:
    cols = _table_date_columns(session, table_name)
    for col in cols:
        try:
            row = session.execute(
                text(f'SELECT MIN("{col}") AS min_d FROM "{table_name}"')
            ).one()
            if row.min_d:
                val = row.min_d
                if hasattr(val, "date"):
                    val = val.date()
                elif isinstance(val, str) and len(val) >= 10:
                    val = date.fromisoformat(val[:10])
                return val
        except Exception:
            session.rollback()
            continue
    return None


def _effective_mode(api_name: str, schema: dict) -> str:
    if api_name in DAILY_BATCH_MODE_OVERRIDES:
        return DAILY_BATCH_MODE_OVERRIDES[api_name]
    profile = resolve_workflow_sync_profile(api_name, schema, batch_mode="backfill")
    return profile.mode


def _generic_backfill_span(
    session: Session,
    table_name: str,
    global_start: date,
    end: date,
) -> tuple[date, date, str]:
    """Gap before existing table min (snapshot / period / ts_code / date_range)."""
    min_d = _table_min_date(session, table_name)
    if min_d and min_d > global_start:
        gap_end = min_d - timedelta(days=1)
        return global_start, gap_end, f"resume gap {global_start}..{gap_end} (table min={min_d})"
    if min_d and min_d <= global_start:
        return end + timedelta(days=1), end, f"already covers {global_start} (min={min_d})"
    return global_start, end, f"full {global_start}..{end}"


def _period_rotation_plan(
    session: Session,
    *,
    span_start: date,
    span_end: date,
    api_name: str,
) -> tuple[int, int, int]:
    """Return (period_count, codes_per_run, rotation_chunks)."""
    period_count = len(_periods_in_range(span_start, span_end))
    if api_name in PERIOD_MARKET_APIS:
        chunks = max(1, (period_count + API_BUDGET - 1) // API_BUDGET)
        return period_count, period_count, chunks
    codes, _ = resolve_stock_codes(
        session, {"stock_codes_table": "tushare_stock_basic"}, max_codes=10_000
    )
    codes_per_run = max(1, API_BUDGET // max(period_count, 1))
    rotations = max(1, (len(codes) + codes_per_run - 1) // codes_per_run)
    return period_count, codes_per_run, rotations


def estimate_chunks(
    session: Session,
    data_type: str,
    api_name: str,
    schema: dict,
    *,
    global_start: date,
    end: date,
    table_name: str,
) -> ChunkPlan:
    mode = _effective_mode(api_name, schema)

    if mode == "trade_date":
        span_start, span_end, note = _trade_date_backfill_span(session, table_name, global_start, end)
        if span_start > span_end:
            return ChunkPlan(data_type, api_name, mode, 0, note)
        days = len(_trading_days_in_range(span_start, span_end))
        chunks = max(1, (days + _chunk_budget() - 1) // _chunk_budget())
        return ChunkPlan(data_type, api_name, mode, chunks, f"{note}; {days} trading days")

    span_start, span_end, note = _generic_backfill_span(session, table_name, global_start, end)
    if span_start > span_end:
        if "already covers" in note:
            return ChunkPlan(data_type, api_name, mode, 0, note)
        return ChunkPlan(data_type, api_name, mode, 0, f"up to date ({note})")

    if mode in ("ts_code", "date_range"):
        codes, _ = resolve_stock_codes(session, {"stock_codes_table": "tushare_stock_basic"}, max_codes=10_000)
        per_run = resolve_rotation_codes(api_name)
        chunks = max(1, (len(codes) + per_run - 1) // per_run)
        return ChunkPlan(data_type, api_name, mode, chunks, f"{note}; ~{len(codes)} codes × {chunks} rotations")

    if mode == "period":
        period_count, codes_per_run, rotations = _period_rotation_plan(
            session, span_start=span_start, span_end=span_end, api_name=api_name
        )
        if api_name in PERIOD_MARKET_APIS:
            return ChunkPlan(
                data_type,
                api_name,
                mode,
                rotations,
                f"{note}; {period_count} periods, market-wide",
            )
        return ChunkPlan(
            data_type,
            api_name,
            mode,
            rotations,
            f"{note}; {period_count} periods, {codes_per_run} codes/run",
        )

    if mode == "snapshot":
        return ChunkPlan(data_type, api_name, mode, 1, note)

    return ChunkPlan(data_type, api_name, mode, 1, f"{note}; mode={mode}")


def _load_schema(session: Session, data_type: str) -> tuple[dict, str]:
    override = session.execute(
        select(TiaOverride).where(TiaOverride.data_type == data_type).limit(1)
    ).scalar_one_or_none()
    if override is None or not override.is_activated:
        raise SystemExit(f"{data_type} 未 L3 激活")
    schema = dict((override.override_json or {}).get("schema") or {})
    table_name = override.table_name or data_type
    return schema, table_name


def _table_row_count(session: Session, table_name: str) -> int | None:
    try:
        return int(session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one())
    except Exception:
        session.rollback()
        return None


def _truncate_table(session: Session, table_name: str) -> int | None:
    """TRUNCATE target fact table; returns row count before truncate."""
    before = _table_row_count(session, table_name)
    session.execute(text(f'TRUNCATE TABLE "{table_name}"'))
    session.commit()
    return before


def _ensure_stock_basic(session: Session) -> None:
    """ts_code / date_range / period strategies need a populated stock_basic."""
    try:
        _, table_name = _load_schema(session, "tushare_stock_basic")
    except SystemExit as exc:
        raise SystemExit("需要先 L3 激活 tushare_stock_basic") from exc
    rows = _table_row_count(session, table_name)
    if not rows:
        raise SystemExit(
            "tushare_stock_basic 为空，按股票轮询的接口无法采集。"
            "请先执行 tier 0（勿清空 stock_basic），或先回填 stock_basic。"
        )


def _table_date_range(session: Session, table_name: str) -> str:
    col = _primary_date_column(session, table_name)
    if not col:
        return "n/a"
    try:
        row = session.execute(
            text(f'SELECT MIN("{col}") AS mn, MAX("{col}") AS mx FROM "{table_name}"')
        ).one()
        mn, mx = _as_date(row.mn), _as_date(row.mx)
        if mn and mx:
            return f"{mn}..{mx}"
    except Exception:
        session.rollback()
    return "n/a"


def _run_collect(
    session: Session,
    *,
    data_type: str,
    api_name: str,
    schema: dict,
    table_name: str,
    start: date,
    end: date,
    stock_code_offset: int = 0,
    log_file: IO[str] | None = None,
    collect_extra: dict | None = None,
) -> tuple[int, int, str]:
    provider, token, source_config, source_id = _resolve_source(session)
    require_tushare_token({"token": token})
    profile = resolve_workflow_sync_profile(api_name, schema, batch_mode="backfill")
    config = resolve_workflow_collect_config(
        schema, profile, batch_mode="backfill", api_name=api_name
    )

    extra = {
                "session": session,
                "provider": provider,
                "token": token,
                "source_config": source_config,
                "max_calls_per_minute": resolve_max_calls_per_minute(source_config),
                "table_name": table_name,
                "stock_codes_table": "tushare_stock_basic",
                "stock_code_offset": stock_code_offset,
                "workflow_schema": schema,
                "workflow_profile": profile,
                "backfill_progress": True,
                "backfill_log_file": log_file,
                **_upsert_extra(),
                "collect_params": {
                    **dict((schema.get("collect") or {})),
                    "max_api_calls_per_run": config.max_api_calls_per_run,
                    "max_codes_per_run": config.max_codes_per_run,
                },
            }
    if collect_extra:
        extra.update(collect_extra)
    result = SyncExecutor().run(
        SyncContext(
            data_type=data_type,
            source_id=source_id or 1,
            start_date=start,
            end_date=end,
            batch_mode="backfill",
            extra=extra,
        )
    )
    session.commit()
    return result.rows_upserted, result.api_calls, result.message or ""


def backfill_one(
    session: Session,
    data_type: str,
    api_name: str,
    *,
    dry_run: bool,
    max_chunks: int | None,
    from_chunk: int = 1,
    log_file: IO[str] | None = None,
) -> tuple[int, bool]:
    log = _logger()
    schema, table_name = _load_schema(session, data_type)
    mode = _effective_mode(api_name, schema)
    global_start = _global_start(session, data_type)
    end = date.today()
    plan = estimate_chunks(session, data_type, api_name, schema, global_start=global_start, end=end, table_name=table_name)
    if plan.chunks == 0:
        log.log(f"[{data_type}] 跳过 — {plan.note}")
        return 0, True
    if dry_run:
        log.log(f"[{data_type}] dry-run mode={mode} chunks={plan.chunks} — {plan.note}")
        return 0, True

    before_range = _table_date_range(session, table_name)
    before_rows = _table_row_count(session, table_name)
    from_chunk = max(1, from_chunk)
    chunks_done = from_chunk - 1
    session_chunks = 0
    total_chunks = plan.chunks
    if max_chunks is not None:
        total_chunks = min(total_chunks, (from_chunk - 1) + max_chunks)
    if from_chunk > 1:
        log.log(f"[{data_type}] 从 chunk {from_chunk} 续跑（跳过前 {from_chunk - 1} 个 chunk）")

    if mode == "trade_date":
        span_start, span_end, _ = _trade_date_backfill_span(session, table_name, global_start, end)
        if span_start > span_end:
            log.log(f"[{data_type}] 已达目标区间")
            return 0, True
        all_days = _trading_days_in_range(span_start, span_end)
        total_chunks = min((len(all_days) + _chunk_budget() - 1) // _chunk_budget(), total_chunks)
        if max_chunks is not None:
            total_chunks = min(total_chunks, max_chunks)
        budget = _chunk_budget()
        start_idx = _chunk_start_offset(from_chunk, budget)
        for i in range(start_idx, len(all_days), budget):
            if max_chunks is not None and session_chunks >= max_chunks:
                break
            chunk_days = all_days[i : i + budget]
            start, chunk_end = chunk_days[0], chunk_days[-1]
            chunks_done += 1
            session_chunks += 1
            t0 = log.chunk_begin(
                data_type,
                chunks_done,
                total_chunks,
                label="trade_date",
                detail=f"{start}..{chunk_end} ({len(chunk_days)} days)",
            )
            rows, calls, msg = _run_collect(
                session,
                data_type=data_type,
                api_name=api_name,
                schema=schema,
                table_name=table_name,
                start=start,
                end=chunk_end,
                log_file=log_file,
            )
            log.chunk_end(
                data_type, chunks_done, total_chunks, started=t0, rows=rows, calls=calls, extra=msg[:60]
            )
            try:
                _finish_rotation_chunk(calls=calls, msg=msg)
            except RuntimeError as exc:
                return _handle_chunk_failure(data_type, chunks_done, exc)
    elif mode in ("ts_code", "date_range"):
        total_codes = _stock_code_total(session)
        rotation_codes = resolve_rotation_codes(api_name)
        offset = _chunk_start_offset(from_chunk, rotation_codes)
        schema_run = _schema_capped(schema, max_codes_per_run=rotation_codes)
        while offset < total_codes:
            if max_chunks is not None and session_chunks >= max_chunks:
                break
            chunks_done += 1
            session_chunks += 1
            t0 = log.chunk_begin(
                data_type,
                chunks_done,
                total_chunks,
                label="rotation",
                detail=f"offset={offset}",
            )
            rows, calls, msg = _run_collect(
                session,
                data_type=data_type,
                api_name=api_name,
                schema=schema_run,
                table_name=table_name,
                start=global_start,
                end=end,
                stock_code_offset=offset,
                log_file=log_file,
            )
            log.chunk_end(
                data_type, chunks_done, total_chunks, started=t0, rows=rows, calls=calls, extra=msg[:60]
            )
            try:
                _finish_rotation_chunk(calls=calls, msg=msg)
            except RuntimeError as exc:
                return _handle_chunk_failure(data_type, chunks_done, exc)
            if calls == 0:
                break
            offset += rotation_codes
    elif mode == "period":
        span_start, span_end, span_note = _generic_backfill_span(
            session, table_name, global_start, end
        )
        if span_start > span_end:
            log.log(f"[{data_type}] 已达目标区间 — {span_note}")
            return 0, True
        period_count, codes_per_run, total_chunks = _period_rotation_plan(
            session, span_start=span_start, span_end=span_end, api_name=api_name
        )
        if max_chunks is not None:
            total_chunks = min(total_chunks, (from_chunk - 1) + max_chunks)
        if api_name in PERIOD_MARKET_APIS:
            if from_chunk > 1:
                log.log(f"[{data_type}] market period 模式仅 1 个 chunk，from_chunk={from_chunk} 已忽略")
            t0 = log.chunk_begin(data_type, 1, total_chunks, label="period", detail="market-wide by end_date")
            rows, calls, msg = _run_collect(
                session,
                data_type=data_type,
                api_name=api_name,
                schema=schema,
                table_name=table_name,
                start=span_start,
                end=span_end,
                log_file=log_file,
            )
            chunks_done = 1
            log.chunk_end(data_type, 1, total_chunks, started=t0, rows=rows, calls=calls, extra=msg[:60])
            try:
                _finish_rotation_chunk(calls=calls, msg=msg)
            except RuntimeError as exc:
                return _handle_chunk_failure(data_type, chunks_done, exc)
        else:
            offset = _chunk_start_offset(from_chunk, codes_per_run)
            total_codes = _stock_code_total(session)
            while offset < total_codes and chunks_done < total_chunks:
                if max_chunks is not None and session_chunks >= max_chunks:
                    break
                chunks_done += 1
                session_chunks += 1
                schema_run = _schema_capped(schema, max_codes_per_run=codes_per_run)
                t0 = log.chunk_begin(
                    data_type,
                    chunks_done,
                    total_chunks,
                    label="period",
                    detail=f"offset={offset} codes/run={codes_per_run}",
                )
                rows, calls, msg = _run_collect(
                    session,
                    data_type=data_type,
                    api_name=api_name,
                    schema=schema_run,
                    table_name=table_name,
                    start=span_start,
                    end=span_end,
                    stock_code_offset=offset,
                    log_file=log_file,
                )
                log.chunk_end(
                    data_type, chunks_done, total_chunks, started=t0, rows=rows, calls=calls
                )
                try:
                    _finish_rotation_chunk(calls=calls, msg=msg)
                except RuntimeError as exc:
                    return _handle_chunk_failure(data_type, chunks_done, exc)
                if calls == 0:
                    break
                offset += codes_per_run
    else:
        if from_chunk > 1:
            log.log(f"[{data_type}] snapshot 模式仅 1 个 chunk，from_chunk={from_chunk} 已忽略")
        t0 = log.chunk_begin(data_type, 1, 1, label="snapshot", detail=str(global_start))
        rows, calls, msg = _run_collect(
            session,
            data_type=data_type,
            api_name=api_name,
            schema=schema,
            table_name=table_name,
            start=global_start,
            end=end,
            log_file=log_file,
        )
        chunks_done = 1
        log.chunk_end(data_type, 1, 1, started=t0, rows=rows, calls=calls, extra=msg[:60])
        try:
            _finish_rotation_chunk(calls=calls, msg=msg)
        except RuntimeError as exc:
            return _handle_chunk_failure(data_type, chunks_done, exc)

    after_range = _table_date_range(session, table_name)
    after_rows = _table_row_count(session, table_name)
    log.log(
        f"[{data_type}] 表 {table_name}: rows {before_rows} -> {after_rows}, "
        f"dates {before_range} -> {after_range}"
    )
    completed = max_chunks is not None or chunks_done >= total_chunks
    if not completed:
        log.log(
            f"[{data_type}] 未完成: chunks {chunks_done}/{total_chunks} "
            f"（可重新运行同一 data_type 续跑）"
        )
    return chunks_done, completed


def list_plan(session: Session) -> None:
    end = date.today()
    print(f"Global sync_start_date target: {_global_start(session, 'tushare_daily')}")
    print(f"Chunk size (trading days): {_chunk_budget()} (max API {API_BUDGET})")
    print(f"{'Tier':<5} {'data_type':<32} {'mode':<14} {'chunks':<7} note")
    print("-" * 90)
    total_chunks = 0
    for tier, data_type, api_name in BACKFILL_PLAN:
        try:
            schema, table_name = _load_schema(session, data_type)
        except SystemExit:
            print(f"{tier:<5} {data_type:<32} {'—':<14} {'—':<7} NOT ACTIVATED")
            continue
        gs = _global_start(session, data_type)
        plan = estimate_chunks(session, data_type, api_name, schema, global_start=gs, end=end, table_name=table_name)
        total_chunks += plan.chunks
        print(f"{tier:<5} {data_type:<32} {plan.mode:<14} {plan.chunks:<7} {plan.note}")
    print("-" * 90)
    print(f"Estimated total chunks (if all gaps): ~{total_chunks}")


def _sum_plan_chunks(session: Session, targets: list[tuple[int, str, str]]) -> int:
    end = date.today()
    total = 0
    for _tier, data_type, api_name in targets:
        try:
            schema, table_name = _load_schema(session, data_type)
            gs = _global_start(session, data_type)
            plan = estimate_chunks(
                session, data_type, api_name, schema, global_start=gs, end=end, table_name=table_name
            )
            total += plan.chunks
        except SystemExit:
            continue
    return max(1, total)


def main() -> int:
    global _LOGGER, _CHUNK_DAYS, _USE_FAST_UPSERT
    parser = argparse.ArgumentParser(description="Chunked history backfill from sync_start_date")
    parser.add_argument("--list", action="store_true", help="Show backfill plan and chunk estimates")
    parser.add_argument("--data-type", action="append", dest="data_types", metavar="TYPE")
    parser.add_argument("--tier", type=int, action="append", help="Run all types in tier (0-4)")
    parser.add_argument("--all", action="store_true", help="Run full plan (all tiers)")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, no API calls")
    parser.add_argument("--max-chunks", type=int, default=None, help="Limit chunks per data_type")
    parser.add_argument(
        "--from-chunk",
        type=int,
        default=1,
        metavar="N",
        help="Start from chunk N (1-based; skip earlier rotations or day batches)",
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=DEFAULT_CHUNK_DAYS,
        help=f"Trading days per API chunk (default {DEFAULT_CHUNK_DAYS}, max {API_BUDGET})",
    )
    parser.add_argument(
        "--fast-upsert",
        action="store_true",
        help="Use execute_values + larger batches (faster but may hang on large flushes)",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Append progress to this file (default: logs/backfill_history.log when executing)",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="TRUNCATE each target table before backfill (clean full reload)",
    )
    args = parser.parse_args()
    if args.from_chunk < 1:
        print("--from-chunk must be >= 1")
        return 1
    _CHUNK_DAYS = max(1, min(args.chunk_days, API_BUDGET))
    _USE_FAST_UPSERT = bool(args.fast_upsert)

    session = _db_session()
    TiaOverrideService().load_all_into_registry_sync(session)

    if args.list or (not args.data_types and not args.tier and not args.all):
        list_plan(session)
        session.close()
        return 0

    targets: list[tuple[int, str, str]] = []
    if args.all:
        targets = BACKFILL_PLAN
    elif args.tier:
        tiers = set(args.tier)
        targets = [t for t in BACKFILL_PLAN if t[0] in tiers]
    if args.data_types:
        wanted = set(args.data_types)
        targets.extend([t for t in BACKFILL_PLAN if t[1] in wanted])

    if not targets:
        print("未选择任何 data_type")
        session.close()
        return 1

    seen: set[str] = set()
    unique_targets: list[tuple[int, str, str]] = []
    for item in targets:
        if item[1] not in seen:
            seen.add(item[1])
            unique_targets.append(item)

    log_path = args.log_file
    if log_path is None and not args.dry_run:
        log_path = DEFAULT_LOG_DIR / "backfill_history.log"

    job = None
    job_svc = None
    job_updater: JobProgressFn | None = None
    if not args.dry_run:
        from app.services.platform.job_service import PlatformJobService

        job_svc = PlatformJobService()
        job = job_svc.create_sync(session, "history_backfill")
        session.commit()

        def job_updater(progress: int, message: str) -> None:
            if job_svc is None or job is None:
                return
            job_svc.update_sync(
                session,
                job.id,
                status="running",
                progress=progress,
                message=message[:480],
            )
            session.commit()

    total_units = _sum_plan_chunks(session, unique_targets)
    _LOGGER = BackfillLogger(
        log_path,
        job_updater=job_updater,
        total_units=total_units,
    )
    log = _logger()
    log_handle = log.log_file_handle()

    log.log(
        f"开始回填 {len(unique_targets)} 个 data_type, chunk_days={_chunk_budget()}, "
        f"upsert={'fast' if _USE_FAST_UPSERT else 'conservative'}, "
        f"total_chunks≈{total_units}"
        f"{' (dry-run)' if args.dry_run else ''}"
        f"{' truncate=on' if args.truncate else ''}"
        + (f" from_chunk={args.from_chunk}" if args.from_chunk > 1 else "")
        + (f" log={log_path}" if log_path else "")
        + (f" job_id={job.id}" if job else "")
    )

    rc = 0
    for idx, (_tier, data_type, api_name) in enumerate(unique_targets, start=1):
        try:
            schema, table_name = _load_schema(session, data_type)
            gs = _global_start(session, data_type)
            mode = _effective_mode(api_name, schema)
            if mode in ("ts_code", "date_range", "period"):
                _ensure_stock_basic(session)
            if args.truncate:
                rows_before = _table_row_count(session, table_name)
                if args.dry_run:
                    log.log(f"TRUNCATE (dry-run) {data_type} table={table_name} rows={rows_before}")
                else:
                    _truncate_table(session, table_name)
                    log.log(f"TRUNCATE {data_type} table={table_name} rows_was={rows_before}")
            plan = estimate_chunks(
                session, data_type, api_name, schema, global_start=gs, end=date.today(), table_name=table_name
            )
            log.table_begin(idx, len(unique_targets), data_type, plan)
            chunks_done, completed = backfill_one(
                session,
                data_type,
                api_name,
                dry_run=args.dry_run,
                max_chunks=args.max_chunks,
                from_chunk=args.from_chunk,
                log_file=log_handle,
            )
            log.table_end(data_type, chunks_done, ok=completed)
            if not completed:
                rc = 1
        except SystemExit as exc:
            log.log(f"SKIP {data_type}: {exc}")
            log.table_end(data_type, 0, ok=False)
            rc = 1
        except Exception as exc:
            log.log(f"FAIL {data_type}: {exc}")
            log.table_end(data_type, 0, ok=False)
            rc = 1

    if job is not None and job_svc is not None:
        job_svc.update_sync(
            session,
            job.id,
            status="success" if rc == 0 else "failed",
            progress=100,
            message="history backfill finished" if rc == 0 else "history backfill failed",
        )
        session.commit()
        log.log(f"platform_job_id={job.id} 可在 GET /api/v1/platform/jobs/{job.id} 查看进度")

    log.log(f"全部结束 exit={rc}")
    session.close()
    log.close()
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
