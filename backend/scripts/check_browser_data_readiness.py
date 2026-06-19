#!/usr/bin/env python3
"""Check Data Browser data readiness — P0 gate + optional P1 extensions."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal
from app.services.query.browser_readiness import BrowserReadinessService


async def check(*, extended: bool) -> int:
    async with AsyncSessionLocal() as session:
        result = await BrowserReadinessService().check(session, extended=extended)

    if extended:
        print("\n--- P1 扩展（申万 / 指数，非门禁）---")
        for item in result.items:
            if item.level != "p1":
                continue
            if item.ok and item.row_count is not None:
                print(f"  OK {item.label}: {item.row_count} rows")

    if result.errors:
        print("Data Browser P0 门禁未通过:")
        for e in result.errors:
            print(f"  - {e}")
        return 1
    if result.warnings:
        print("Data Browser P0 门禁通过（有提示）:")
        for w in result.warnings:
            print(f"  ! {w}")
    else:
        print("Data Browser P0 门禁通过")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Check Data Browser readiness")
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Also report P1 Shenwan / index tables (warnings only)",
    )
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check(extended=args.extended)))


if __name__ == "__main__":
    main()
