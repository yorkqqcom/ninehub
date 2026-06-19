"""Data Browser data readiness checks — P0 gate + P1 extensions."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.registry import get_data_type_entry
from app.schemas.query_browser import BrowserReadinessItem, BrowserReadinessResponse
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

BACKFILL_SCRIPT = "backfill_browser_daily.py"
STOCK_BASIC_RESYNC_SCRIPT = "resync_stock_basic.py"


async def _table_row_count(session: AsyncSession, table_name: str) -> int | None:
    try:
        result = await session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        return int(result.scalar_one())
    except Exception:
        return None


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
                else:
                    ok = True
                    if data_type == "tushare_stock_basic":
                        stock_basic_count = row_count
                    elif data_type == "tushare_daily":
                        daily_count = row_count

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
            and daily_count < stock_basic_count * 0.5
        ):
            msg = (
                f"daily 覆盖率偏低（{daily_count}/{stock_basic_count}），"
                f"请运行 python scripts/{BACKFILL_SCRIPT}"
            )
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
                if int(ex_cnt.scalar_one() or 0) == 0:
                    warnings.append(
                        "stock_basic 关键列（如 exchange/name）未采集，"
                        f"请运行 python scripts/{STOCK_BASIC_RESYNC_SCRIPT}"
                    )
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
