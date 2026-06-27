"""Data Browser data readiness checks — P0 gate + P1 extensions."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.registry import get_data_type_entry
from app.schemas.query_browser import BrowserReadinessItem, BrowserReadinessResponse
from app.services.platform.service import PlatformService
from app.services.tia.override_service import TiaOverrideService

P0_TYPES: tuple[tuple[str, str], ...] = (
    ("tushare_stock_basic", "股票基础"),
    ("tushare_daily", "日线行情"),
    ("tushare_adj_factor", "复权因子"),
    ("tushare_trade_cal", "交易日历"),
)

P1_TYPES: tuple[tuple[str, str, int, str], ...] = (
    ("tushare_index_classify", "申万行业树", 31, "bootstrap_browser_shenwan.py"),
    ("tushare_index_member_all", "申万成分", 5000, "bootstrap_browser_shenwan.py"),
    ("tushare_index_weight", "指数成分", 200, "bootstrap_browser_index.py"),
)

BACKFILL_SCRIPT = "run_backfill_history.py --data-type tushare_daily"
STOCK_BASIC_RESYNC_SCRIPT = "resync_stock_basic.py"
MIN_DAILY_TRADING_DAYS = 20
MIN_DAILY_ROWS_PER_STOCK = 10
MIN_DAILY_MARKET_COVERAGE = 0.8


async def _daily_full_market_day_ratio(
    session: AsyncSession, table_name: str, stock_basic_count: int
) -> tuple[int, int] | None:
    if not stock_basic_count:
        return None
    min_rows = max(1, int(stock_basic_count * MIN_DAILY_MARKET_COVERAGE))
    try:
        row = (
            await session.execute(
                text(
                    f"""
SELECT COUNT(*) AS total_days,
       COUNT(*) FILTER (WHERE cnt >= :min_rows) AS full_days
FROM (
  SELECT COUNT(*) AS cnt FROM "{table_name}" GROUP BY trade_date
) t
"""
                ),
                {"min_rows": min_rows},
            )
        ).one()
        return int(row.full_days or 0), int(row.total_days or 0)
    except Exception:
        return None


async def _table_row_count(session: AsyncSession, table_name: str) -> int | None:
    try:
        result = await session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        return int(result.scalar_one())
    except Exception:
        return None


async def _daily_coverage_stats(
    session: AsyncSession, table_name: str
) -> tuple[date | None, date | None, int] | None:
    try:
        row = (
            await session.execute(
                text(
                    f'SELECT MIN(trade_date) AS mn, MAX(trade_date) AS mx, '
                    f'COUNT(DISTINCT trade_date) AS nd FROM "{table_name}"'
                )
            )
        ).one()
    except Exception:
        return None
    min_d = row.mn.date() if row.mn is not None and hasattr(row.mn, "date") else row.mn
    max_d = row.mx.date() if row.mx is not None and hasattr(row.mx, "date") else row.mx
    return min_d, max_d, int(row.nd or 0)


async def _validate_daily_coverage(
    session: AsyncSession,
    *,
    table_name: str,
    row_count: int,
    stock_basic_count: int | None,
) -> tuple[bool, str | None]:
    stats = await _daily_coverage_stats(session, table_name)
    if stats is None:
        return False, "无法读取 trade_date 统计"
    min_d, _max_d, distinct_days = stats
    sync_start = date.fromisoformat(
        await PlatformService().resolve_sync_start_date(session, "tushare_daily")
    )
    issues: list[str] = []
    if distinct_days < MIN_DAILY_TRADING_DAYS:
        issues.append(f"仅覆盖 {distinct_days} 个交易日")
    if min_d and min_d > sync_start + timedelta(days=30):
        issues.append(f"最早日期 {min_d} 晚于 sync_start {sync_start}")
    if stock_basic_count and row_count < stock_basic_count * MIN_DAILY_ROWS_PER_STOCK:
        issues.append(
            f"行数 {row_count} 偏低（预期约 {stock_basic_count} 股 × 多个交易日）"
        )
    coverage = await _daily_full_market_day_ratio(
        session, table_name, stock_basic_count or 0
    )
    if coverage is not None:
        full_days, total_days = coverage
        if total_days and full_days < total_days * MIN_DAILY_MARKET_COVERAGE:
            issues.append(
                f"仅 {full_days}/{total_days} 个交易日达到全市场覆盖"
                f"（每日需 ≥ {int((stock_basic_count or 0) * MIN_DAILY_MARKET_COVERAGE)} 行）"
            )
    if not issues:
        return True, None
    return False, "；".join(issues)


class BrowserReadinessService:
    async def check(self, session: AsyncSession, *, extended: bool = True) -> BrowserReadinessResponse:
        await TiaOverrideService().load_all_into_registry(session)
        items: list[BrowserReadinessItem] = []
        errors: list[str] = []
        warnings: list[str] = []
        stock_basic_count: int | None = None
        daily_count: int | None = None

        for data_type, label in P0_TYPES:
            entry = get_data_type_entry(data_type)
            activated = entry is not None and entry.is_activated
            table_name = entry.table_name if entry else None
            row_count: int | None = None
            ok = False
            message: str | None = None
            script: str | None = None

            if not activated:
                message = "未激活"
                errors.append(f"未激活: {data_type}")
            elif not table_name:
                message = "无表名"
                errors.append(f"无表名: {data_type}")
            else:
                row_count = await _table_row_count(session, table_name)
                if row_count is None:
                    message = "表不可读"
                    errors.append(f"表不可读: {table_name}")
                elif row_count == 0:
                    message = "表无数据"
                    errors.append(f"表无数据: {table_name}")
                elif data_type == "tushare_daily":
                    daily_count = row_count
                    coverage_ok, coverage_msg = await _validate_daily_coverage(
                        session,
                        table_name=table_name,
                        row_count=row_count,
                        stock_basic_count=stock_basic_count,
                    )
                    if coverage_ok:
                        ok = True
                    else:
                        message = coverage_msg
                        script = BACKFILL_SCRIPT
                        errors.append(f"日线行情: {coverage_msg}")
                else:
                    ok = True
                    if data_type == "tushare_stock_basic":
                        stock_basic_count = row_count

            items.append(
                BrowserReadinessItem(
                    data_type=data_type,
                    label=label,
                    level="p0",
                    activated=activated,
                    table_name=table_name,
                    row_count=row_count,
                    ok=ok,
                    message=message,
                    suggested_script=script,
                )
            )

        if (
            stock_basic_count
            and daily_count is not None
            and daily_count < stock_basic_count * MIN_DAILY_ROWS_PER_STOCK
        ):
            msg = (
                f"daily 历史覆盖不足（{daily_count} 行 / {stock_basic_count} 股），"
                f"请运行 python scripts/{BACKFILL_SCRIPT}"
            )
            if msg not in warnings and msg not in errors:
                warnings.append(msg)

        sb_entry = get_data_type_entry("tushare_stock_basic")
        if sb_entry and sb_entry.table_name and stock_basic_count:
            try:
                ex_cnt = await session.execute(
                    text(
                        f'SELECT COUNT(*) FILTER (WHERE exchange IS NOT NULL) '
                        f'FROM "{sb_entry.table_name}"'
                    )
                )
                ex_non_null = int(ex_cnt.scalar_one() or 0)
                if ex_non_null == 0:
                    nm_cnt = await session.execute(
                        text(
                            f'SELECT COUNT(*) FILTER (WHERE name IS NOT NULL) '
                            f'FROM "{sb_entry.table_name}"'
                        )
                    )
                    name_non_null = int(nm_cnt.scalar_one() or 0)
                    if name_non_null == 0:
                        msg = (
                            "stock_basic 关键列 name 未采集，"
                            f"请运行 python scripts/{STOCK_BASIC_RESYNC_SCRIPT}"
                        )
                    else:
                        msg = (
                            "stock_basic 关键列 exchange 未采集（Tushare 默认响应不含该列），"
                            f"请运行 python scripts/{STOCK_BASIC_RESYNC_SCRIPT}"
                        )
                    warnings.append(msg)
            except Exception:
                pass

        if extended:
            for data_type, label, min_rows, script in P1_TYPES:
                entry = get_data_type_entry(data_type)
                activated = entry is not None and entry.is_activated
                table_name = entry.table_name if entry else None
                row_count: int | None = None
                ok = False
                message: str | None = None

                if not activated:
                    message = "未激活"
                    warnings.append(f"P1 未激活 {label} ({data_type})")
                elif not table_name:
                    message = "无表"
                    warnings.append(f"P1 无表 {label}")
                else:
                    row_count = await _table_row_count(session, table_name)
                    if row_count is None:
                        message = "表不可读"
                        warnings.append(f"P1 表不可读 {table_name}")
                    elif row_count < min_rows:
                        message = f"行数偏低 ({row_count} < {min_rows})"
                        warnings.append(
                            f"P1 {label} {message}，可运行 python scripts/{script}"
                        )
                    else:
                        ok = True

                items.append(
                    BrowserReadinessItem(
                        data_type=data_type,
                        label=label,
                        level="p1",
                        activated=activated,
                        table_name=table_name,
                        row_count=row_count,
                        min_rows=min_rows,
                        ok=ok,
                        message=message,
                        suggested_script=script if not ok else None,
                    )
                )

            try:
                sw_l1 = await session.execute(
                    text(
                        "SELECT COUNT(*) FROM tushare_index_classify "
                        "WHERE level='L1' AND src='SW2021'"
                    )
                )
                l1_count = int(sw_l1.scalar_one())
                if l1_count < 31:
                    warnings.append(
                        f"申万一级行业仅 {l1_count}/31，"
                        "请运行 bootstrap_browser_shenwan.py --collect-only"
                    )
            except Exception:
                pass

        return BrowserReadinessResponse(
            p0_ok=len(errors) == 0,
            items=items,
            warnings=warnings,
            errors=errors,
        )
