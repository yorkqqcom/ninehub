#!/usr/bin/env python3
"""CLI: trigger TDX vipdoc import via sync task or direct Sidecar call."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from browser_bootstrap_lib import db_session
from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.sync_task import SyncTask  # noqa: F401
from app.services.collectors.tdx_sidecar import TdxSidecarClient
from app.services.tia.credentials_tdx import resolve_tdx_collect_credentials
from app.tasks.sync_tasks import run_collect


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date: {value}")


def run_via_task(session: Session, data_type: str) -> dict:
    task_id = session.execute(
        select(SyncTask.id).where(SyncTask.data_type == data_type).limit(1)
    ).scalar_one_or_none()
    if task_id is None:
        task_id = session.execute(
            text("select id from sync_tasks where data_type=:dt limit 1"),
            {"dt": data_type},
        ).scalar()
    if task_id is None:
        raise RuntimeError(f"No sync_task for {data_type}; run bootstrap_tdx_bar_1d.py first")
    print(f"Collect via sync_task id={task_id} data_type={data_type}")
    return run_collect(int(task_id))


def run_via_sidecar(
    session: Session,
    *,
    period: str,
    start_date: date | None,
    end_date: date | None,
    limit_files: int | None,
) -> None:
    creds = resolve_tdx_collect_credentials(session, None)
    client = TdxSidecarClient(creds["base_url"], creds.get("api_token"))
    cfg = creds.get("source_config") or creds
    df, meta = client.vipdoc_import(
        period=period,
        start_date=start_date,
        end_date=end_date,
        limit_files=limit_files,
        install_root=cfg.get("install_root"),
        paths=cfg.get("paths"),
    )
    print(f"Sidecar import rows={len(df)} meta={meta}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Import TDX vipdoc bars")
    parser.add_argument("--data-type", default="tdx_bar_1d")
    parser.add_argument("--period", default="1d", choices=("1d", "1m", "5m"))
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--limit-files", type=int, default=None)
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Call Sidecar directly instead of sync_task",
    )
    args = parser.parse_args()
    start = _parse_date(args.start_date)
    end = _parse_date(args.end_date)
    with db_session() as session:
        if args.direct:
            run_via_sidecar(
                session,
                period=args.period,
                start_date=start,
                end_date=end,
                limit_files=args.limit_files,
            )
        else:
            result = run_via_task(session, args.data_type)
            print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
