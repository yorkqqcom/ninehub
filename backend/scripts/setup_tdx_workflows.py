#!/usr/bin/env python3
"""Post-L3 setup for TDX Sidecar collect workflows.

Usage:
  python scripts/setup_tdx_workflows.py --check-only
  python scripts/setup_tdx_workflows.py
  python scripts/setup_tdx_workflows.py --replace-workflows
  python scripts/setup_tdx_workflows.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import sync_engine
from app.models.data_source import DataSource
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal

TDX_WORKFLOW_APIS = ("bar_1d", "bar_1m", "bar_5m", "concept_index", "concept_member")
TDX_DATA_TYPES = tuple(f"tdx_{api}" for api in TDX_WORKFLOW_APIS)


def _load_script_module(filename: str):
    path = BACKEND_ROOT / "scripts" / filename
    name = f"_ninehub_script_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _preflight(session: Session) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []

    ds = session.execute(
        select(DataSource)
        .where(DataSource.provider == "tdx", DataSource.status == "active")
        .order_by(DataSource.id.asc())
        .limit(1)
    ).scalar_one_or_none()
    if ds is None:
        errors.append("无 active TDX 数据源（请在 /sources 配置 Sidecar base_url）")
    else:
        cfg = ds.config or {}
        base_url = (cfg.get("base_url") or "").strip()
        if not base_url:
            errors.append(f"TDX 数据源 {ds.name!r} 未配置 config.base_url")
        else:
            print(f"TDX source: id={ds.id} name={ds.name} base_url={base_url}")

    override_rows = session.execute(
        select(TiaOverride.api_name).where(TiaOverride.api_name.in_(TDX_WORKFLOW_APIS))
    ).scalars().all()
    missing = sorted(set(TDX_WORKFLOW_APIS) - set(override_rows))
    if missing:
        applied = session.execute(
            select(TiaProposal.api_name).where(
                TiaProposal.status == "applied",
                TiaProposal.data_type.in_(TDX_DATA_TYPES),
            )
        ).scalars().all()
        if not applied:
            errors.append(
                "TDX 接口未 L3 激活：请在「提案治理」完成 TDX 扫描与 L3，或运行 "
                "python scripts/bootstrap_tdx_bar_1d.py"
            )
        elif missing:
            warnings.append(
                f"tia_overrides 缺少 {len(missing)} 个 API（工作流节点可能 stub）: "
                + ", ".join(missing)
            )
    else:
        print(f"tia_overrides: {len(override_rows)}/{len(TDX_WORKFLOW_APIS)} TDX APIs OK")

    wf_count = session.scalar(
        select(func.count())
        .select_from(DataSource)
        .where(DataSource.provider == "tdx")
    )
    if not wf_count:
        warnings.append("无 TDX 数据源记录")

    return warnings, errors


async def _apply_and_seed(*, dry_run: bool, replace_workflows: bool) -> None:
    apply_mod = _load_script_module("apply_tdx_workflow_batch.py")
    seed_mod = _load_script_module("seed_tdx_workflows.py")
    await apply_mod.apply(dry_run=dry_run)
    if dry_run:
        print("Dry run: skip seed_tdx_workflows")
        return
    await seed_mod.seed(replace=replace_workflows)


def main() -> int:
    parser = argparse.ArgumentParser(description="TDX Sidecar workflow setup (post-L3)")
    parser.add_argument("--check-only", action="store_true", help="Preflight only")
    parser.add_argument("--dry-run", action="store_true", help="Preview override patches")
    parser.add_argument(
        "--replace-workflows",
        action="store_true",
        help="Replace existing TDX* published workflows",
    )
    args = parser.parse_args()

    with Session(sync_engine) as session:
        warnings, errors = _preflight(session)
        for w in warnings:
            print(f"WARN: {w}")
        if errors:
            for e in errors:
                print(f"ERROR: {e}")
            return 1
        if args.check_only:
            print("\nPreflight OK (--check-only)")
            return 0

    asyncio.run(_apply_and_seed(dry_run=args.dry_run, replace_workflows=args.replace_workflows))

    print("\n--- Done ---")
    if not args.dry_run:
        print("日批: Celery Beat 或工作流页手动运行（batch_mode=daily）")
        print("历史: 工作流 debug/backfill 或 sync_tasks 手动 backfill")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
