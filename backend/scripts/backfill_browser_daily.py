#!/usr/bin/env python3
"""Backfill tushare_daily for Data Browser — trade_date mode (full market per day)."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal  # noqa: F401
from app.models.user import User  # noqa: F401
from app.services.tia.credentials import require_tushare_token, resolve_tushare_collect_credentials
from app.services.tia.override_service import TiaOverrideService
from app.services.tushare.source_quota import resolve_max_calls_per_minute
from app.services.workflow.collect_batch import resolve_workflow_sync_profile
from app.sync.executor import SyncExecutor
from app.sync.handlers import SyncContext

DATA_TYPE = "tushare_daily"
API_NAME = "daily"


def _db_session() -> Session:
    url = os.environ.get(
        "DATABASE_URL", "postgresql://ninehub:ninehub@127.0.0.1:5432/ninehub"
    ).replace("+asyncpg", "")
    return sessionmaker(bind=create_engine(url))()


def _trading_window(session: Session, trading_days: int) -> tuple[date, date]:
    from app.services.workflow.collect_batch import _trading_days_before

    end = date.today()
    start = _trading_days_before(end, max(1, trading_days))
    return start, end


def backfill(trading_days: int = 5) -> int:
    session = _db_session()
    TiaOverrideService().load_all_into_registry_sync(session)

    override = session.execute(
        select(TiaOverride).where(TiaOverride.data_type == DATA_TYPE).limit(1)
    ).scalar_one_or_none()
    if override is None or not override.is_activated:
        print(f"{DATA_TYPE} 未 L3 激活，请先运行 bootstrap_browser_p0.py")
        return 1

    schema = dict((override.override_json or {}).get("schema") or {})
    profile = resolve_workflow_sync_profile(API_NAME, schema, batch_mode="daily")
    start, end = _trading_window(session, trading_days)

    provider, token, source_config, source_id = _resolve_source(session)
    require_tushare_token({"token": token})

    from app.catalog.registry import get_data_type_entry

    entry = get_data_type_entry(DATA_TYPE)
    table_name = override.table_name or (entry.table_name if entry else DATA_TYPE)

    before = session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
    print(f"回填 {API_NAME} mode={profile.mode} {start}..{end}（表内 {before} 行）")

    result = SyncExecutor().run(
        SyncContext(
            data_type=DATA_TYPE,
            source_id=source_id or 1,
            start_date=start,
            end_date=end,
            batch_mode="daily",
            extra={
                "session": session,
                "provider": provider,
                "token": token,
                "source_config": source_config,
                "max_calls_per_minute": resolve_max_calls_per_minute(source_config),
                "table_name": table_name,
                "workflow_schema": schema,
                "workflow_profile": profile,
            },
        )
    )
    session.commit()

    after = session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
    print(
        f"完成：upserted={result.rows_upserted} api_calls={result.api_calls} "
        f"表内 {before} -> {after} 行"
    )
    if result.message:
        print(f"message: {result.message}")
    session.close()
    return 0 if result.rows_upserted > 0 else 1


def _resolve_source(session: Session) -> tuple[str, str, dict, int | None]:
    creds = resolve_tushare_collect_credentials(session)
    return (
        str(creds.get("provider") or "tushare"),
        str(creds.get("token") or ""),
        dict(creds.get("source_config") or {}),
        creds.get("source_id"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill daily OHLC for Data Browser")
    parser.add_argument(
        "--days",
        type=int,
        default=5,
        help="Number of recent trading days to pull (default 5)",
    )
    args = parser.parse_args()
    raise SystemExit(backfill(trading_days=args.days))


if __name__ == "__main__":
    main()
