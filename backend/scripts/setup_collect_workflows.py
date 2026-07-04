#!/usr/bin/env python3
"""Post-L3 setup for 2000-point Tushare collect: overrides, workflows, readiness check.

Run after TIA L3 activation (31 APIs). Does NOT activate proposals or call Tushare.

Usage:
  python scripts/setup_collect_workflows.py --check-only
  python scripts/setup_collect_workflows.py
  python scripts/setup_collect_workflows.py --migrate --replace-workflows
  python scripts/setup_collect_workflows.py --backfill-plan
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import subprocess
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import sync_engine
from app.models.data_source import DataSource
from app.models.tia_override import TiaOverride
from app.services.tia.credentials import resolve_tushare_scan_credentials
from app.services.tushare.source_quota import points_to_max_calls_per_minute
from app.services.workflow.collect_batch import TUSHARE_WORKFLOW_APIS

MIN_ACCOUNT_POINTS = 2000
WORKFLOW_APIS = list(TUSHARE_WORKFLOW_APIS)


def _load_script_module(filename: str):
    path = BACKEND_ROOT / "scripts" / filename
    name = f"_ninehub_script_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run_alembic() -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        check=True,
    )
    print("Alembic migrations applied (head).")


def _preflight(session: Session, *, min_points: int) -> tuple[list[str], list[str]]:
    """Return (warnings, errors)."""
    warnings: list[str] = []
    errors: list[str] = []

    creds = resolve_tushare_scan_credentials(session)
    points = int(creds.get("account_points") or 0)
    tier_cap = points_to_max_calls_per_minute(points)

    if not creds.get("token"):
        errors.append("未配置 Tushare Token（数据源或 TUSHARE_TOKEN）")
    elif points < min_points:
        errors.append(f"账户积分 {points} < {min_points}；A 股工作流多数接口需 2000 积分")
    else:
        src = creds.get("source_name") or "env"
        print(
            f"Tushare: source={src} points={points} "
            f"tier={tier_cap}/min (workflow budget 200/run)"
        )

    override_rows = session.execute(
        select(TiaOverride.api_name).where(TiaOverride.api_name.in_(WORKFLOW_APIS))
    ).scalars().all()
    missing = sorted(set(WORKFLOW_APIS) - set(override_rows))
    if missing:
        errors.append(
            f"tia_overrides 缺少 {len(missing)} 个工作流 API（须先 L3 激活）: "
            + ", ".join(missing[:8])
            + (" …" if len(missing) > 8 else "")
        )
    else:
        print(f"tia_overrides: {len(override_rows)}/{len(WORKFLOW_APIS)} workflow APIs OK")

    ds_count = session.scalar(
        select(func.count()).select_from(DataSource).where(DataSource.provider == "tushare")
    )
    if not ds_count:
        warnings.append("无 Tushare 数据源记录；脚本回退 .env，生产请在 UI 配置")

    return warnings, errors


def _print_backfill_plan(session: Session) -> None:
    from app.services.tia.override_service import TiaOverrideService

    mod = _load_script_module("run_backfill_history.py")
    TiaOverrideService().load_all_into_registry_sync(session)
    try:
        mod.list_plan(session)
    finally:
        session.rollback()


async def _apply_and_seed(*, dry_run: bool, replace_workflows: bool) -> None:
    apply_mod = _load_script_module("apply_workflow_daily_batch.py")
    seed_mod = _load_script_module("seed_tia_workflows.py")
    await apply_mod.apply(dry_run=dry_run)
    if dry_run:
        print("Dry run: skip seed_tia_workflows")
        return
    await seed_mod.seed(replace=replace_workflows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Post-L3 workflow collect setup (2000 pts)")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Preflight only; do not write overrides or workflows",
    )
    parser.add_argument(
        "--migrate",
        action="store_true",
        help="Run alembic upgrade head before setup (013–015 schema patches)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview apply_workflow_daily_batch only",
    )
    parser.add_argument(
        "--replace-workflows",
        action="store_true",
        help="Replace existing 01–05 TIA workflows",
    )
    parser.add_argument(
        "--backfill-plan",
        action="store_true",
        help="After setup, print run_backfill_history chunk estimates",
    )
    parser.add_argument(
        "--min-points",
        type=int,
        default=MIN_ACCOUNT_POINTS,
        help=f"Required account points (default {MIN_ACCOUNT_POINTS})",
    )
    args = parser.parse_args()

    with Session(sync_engine) as session:
        warnings, errors = _preflight(session, min_points=args.min_points)
        for w in warnings:
            print(f"WARN: {w}")
        if errors:
            for e in errors:
                print(f"ERROR: {e}")
            print("\nFix prerequisites then re-run. See backend/README.md §2000 积分 A 股采集部署")
            return 1

        if args.check_only:
            print("\nPreflight OK (--check-only)")
            if args.backfill_plan:
                print("\n--- Backfill plan ---")
                _print_backfill_plan(session)
            return 0

    if args.migrate:
        _run_alembic()

    asyncio.run(_apply_and_seed(dry_run=args.dry_run, replace_workflows=args.replace_workflows))

    if args.backfill_plan and not args.dry_run:
        with Session(sync_engine) as session:
            print("\n--- Backfill plan (next: run_backfill_history.py) ---")
            _print_backfill_plan(session)

    print("\n--- Done ---")
    if not args.dry_run:
        print("Daily: Celery Beat / manual workflow run (batch_mode=daily)")
        print("History: python scripts/run_backfill_history.py --list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
