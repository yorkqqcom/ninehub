#!/usr/bin/env python3
"""Bootstrap index constituents for Data Browser (沪深300 / 中证500).

Uses index_weight (doc 96, 2000 pts) — monthly index constituents.
NOT index_member (doc 72) which is for 申万行业指数代码.

Run:
  cd backend && python scripts/bootstrap_browser_index.py
  python scripts/bootstrap_browser_index.py --collect-only
"""

from __future__ import annotations

import argparse
import sys
from calendar import monthrange
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from browser_bootstrap_lib import (
    activate_sync,
    approve_if_pending,
    check_account_points,
    db_session,
    ensure_proposal,
    get_override,
    row_count,
    schema_of,
)
from app.services.collectors.tushare import TushareCollector
from app.services.tia.credentials import require_tushare_token, resolve_tushare_scan_credentials
from app.services.tia.override_service import TiaOverrideService
from app.services.tia.tia_data_loader import TiaDataLoader

INDEX_API = "index_weight"
MIN_POINTS = 2000
# Tushare index_code → label (399300.SZ 兼容沪深300)
INDEX_TARGETS: dict[str, str] = {
    "399300.SZ": "沪深300",
    "000905.SH": "中证500",
}
INDEX_WEIGHT_UNIQUE_KEYS = ["index_code", "stock_code", "trade_date"]


def _current_month_range(offset_months: int = 0) -> tuple[str, str]:
    today = date.today()
    month = today.month - offset_months
    year = today.year
    while month <= 0:
        month += 12
        year -= 1
    start = date(year, month, 1)
    last_day = monthrange(year, month)[1]
    end = date(year, month, last_day)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _drop_stale_index_weight_uniques(session, table: str) -> None:
    insp = __import__("sqlalchemy").inspect(session.get_bind())
    want = INDEX_WEIGHT_UNIQUE_KEYS
    for uc in insp.get_unique_constraints(table):
        cols = uc.get("column_names") or []
        if cols != want:
            name = uc["name"]
            session.execute(text(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"'))
            session.commit()
            print(f"  dropped stale unique constraint {name} on {cols}")
    for idx in insp.get_indexes(table):
        if not idx.get("unique"):
            continue
        cols = idx.get("column_names") or []
        if cols == want:
            continue
        name = idx["name"]
        session.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
        session.commit()
        print(f"  dropped stale unique index {name} on {cols}")


def _repair_index_weight_schema(session) -> None:
    override = get_override(session, INDEX_API)
    if override is None:
        return
    table = override.table_name or "tushare_index_weight"
    oj = dict(override.override_json or {})
    schema = dict(oj.get("schema") or {})
    columns: list[dict] = []
    for col in schema.get("columns") or []:
        c = dict(col)
        if c.get("key") == "con_code" or c.get("api_field") == "con_code":
            c["key"] = "stock_code"
            c["api_field"] = "con_code"
        columns.append(c)
    schema["columns"] = columns
    field_mappings = dict(schema.get("field_mappings") or {})
    if "con_code" in field_mappings:
        field_mappings.pop("con_code", None)
    field_mappings["con_code"] = "stock_code"
    schema["field_mappings"] = field_mappings
    schema["unique_keys"] = list(INDEX_WEIGHT_UNIQUE_KEYS)
    schema["api_name"] = INDEX_API
    oj["schema"] = schema
    override.override_json = oj
    session.commit()
    bind = session.get_bind()
    insp_cols = {
        c["name"]
        for c in __import__("sqlalchemy").inspect(bind).get_columns(table)
    }
    if "con_code" in insp_cols and "stock_code" not in insp_cols:
        session.execute(text(f'ALTER TABLE "{table}" RENAME COLUMN con_code TO stock_code'))
        session.commit()
        print(f"  renamed {table}.con_code -> stock_code")
    _drop_stale_index_weight_uniques(session, table)
    uq_name = f"uq_{table}_index_stock_date"
    session.execute(
        text(
            f'CREATE UNIQUE INDEX IF NOT EXISTS "{uq_name}" '
            f'ON "{table}" (index_code, stock_code, trade_date)'
        )
    )
    session.commit()
    print(f"  ensured unique index {uq_name}")
    print(f"  repaired unique_keys -> {schema['unique_keys']}")


def _collect_index_weight(
    session,
    collector: TushareCollector,
    loader: TiaDataLoader,
    *,
    skip_repair: bool = False,
) -> int:
    override = get_override(session, INDEX_API)
    if override is None or not override.is_activated:
        raise RuntimeError("index_weight not activated")
    if not skip_repair:
        _repair_index_weight_schema(session)
    schema = schema_of(get_override(session, INDEX_API) or override)
    table = override.table_name or "tushare_index_weight"
    frames: list[pd.DataFrame] = []
    for index_code, label in INDEX_TARGETS.items():
        for offset in (0, 1):
            start_date, end_date = _current_month_range(offset)
            print(f"  index_weight {index_code} ({label}) {start_date}..{end_date} …")
            df = collector._call_pro(  # noqa: SLF001
                INDEX_API,
                index_code=index_code,
                start_date=start_date,
                end_date=end_date,
            )
            if df is not None and not df.empty:
                frames.append(df)
                print(f"    -> {len(df)} rows")
                break
            print("    -> empty")
    if not frames:
        return 0
    merged = pd.concat(frames, ignore_index=True)
    session.execute(text(f'TRUNCATE TABLE "{table}"'))
    session.commit()
    count = loader.upsert_dataframe(session, table, schema, merged)
    session.commit()
    print(f"  index_weight upserted {count} rows into {table}")
    return count


def bootstrap(*, activate: bool, collect: bool, skip_repair: bool = False) -> int:
    session = db_session()
    failed = 0

    print("=== Index bootstrap (index_weight) ===")
    print(f"  targets: {', '.join(f'{k} {v}' for k, v in INDEX_TARGETS.items())}")

    if collect:
        try:
            check_account_points(session, MIN_POINTS, "index_weight")
        except Exception as exc:
            print(f"ERROR credentials: {exc}")
            session.close()
            return 1

    if activate:
        print(f"\n=== activate {INDEX_API} ===")
        try:
            proposal = ensure_proposal(session, INDEX_API, reason="browser_index_bootstrap")
            print(f"  proposal id={proposal.id} status={proposal.status}")
            if proposal.status != "applied":
                approve_if_pending(session, proposal)
                session.commit()
                reapply = proposal.status in ("applied", "failed")
                result = activate_sync(session, proposal.id, reapply=reapply)
                status = session.execute(
                    text("select status from tia_proposals where id=:id"),
                    {"id": proposal.id},
                ).scalar()
                print(f"  activation -> {status}, data_type={result.get('data_type')}")
                if status != "applied":
                    failed += 1
        except Exception as exc:
            session.rollback()
            failed += 1
            print(f"  ERROR: {exc}")

    if collect:
        print("\n=== collect index_weight ===")
        TiaOverrideService().load_all_into_registry_sync(session)
        creds = resolve_tushare_scan_credentials(session)
        token = require_tushare_token(creds)
        mcpm = creds.get("max_calls_per_minute")
        collector = TushareCollector(
            token=token,
            max_calls_per_minute=int(mcpm) if mcpm else None,
        )
        try:
            _collect_index_weight(
                session, collector, TiaDataLoader(), skip_repair=skip_repair
            )
        except Exception as exc:
            failed += 1
            session.rollback()
            print(f"  ERROR: {exc}")

    print("\n=== readiness ===")
    ov = get_override(session, INDEX_API)
    if ov and ov.table_name:
        total = row_count(session, ov.table_name)
        print(f"  {ov.table_name}: {total} rows")
        for code in INDEX_TARGETS:
            try:
                cnt = session.execute(
                    text(
                        f'SELECT COUNT(DISTINCT stock_code) FROM "{ov.table_name}" '
                        "WHERE index_code = :c"
                    ),
                    {"c": code},
                ).scalar_one()
                print(f"    {code}: {cnt} constituents")
            except Exception:
                pass

    session.close()
    print(f"\nDone. failed={failed}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap index_weight for Data Browser")
    parser.add_argument("--activate-only", action="store_true")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument(
        "--skip-repair",
        action="store_true",
        help="Skip schema/DDL repair (use when unique_keys already fixed in DB)",
    )
    args = parser.parse_args()
    raise SystemExit(
        bootstrap(
            activate=not args.collect_only,
            collect=not args.activate_only,
            skip_repair=args.skip_repair,
        )
    )


if __name__ == "__main__":
    main()
