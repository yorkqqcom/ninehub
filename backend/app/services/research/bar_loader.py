"""Load adjusted daily OHLC for backtest universe."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from sqlalchemy import MetaData, Table, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.registry import get_data_type_entry
from app.core.exceptions import ValidationError
from app.services.query.adj_price import apply_adjust
from app.services.research.constants import OHLC_KEYS


class BarLoader:
    async def load(
        self,
        session: AsyncSession,
        codes: list[str],
        start: date,
        end: date,
        *,
        adjust: str = "qfq",
    ) -> dict[str, pd.DataFrame]:
        daily_entry = get_data_type_entry("tushare_daily")
        if not daily_entry or not daily_entry.table_name:
            raise ValidationError("日线未激活", details={"code": "BACKTEST_DAILY_UNAVAILABLE"})
        daily = await self._reflect(session, daily_entry.table_name)
        if daily is None:
            raise ValidationError("日线表不可读", details={"code": "BACKTEST_DAILY_UNAVAILABLE"})

        code_col = "stock_code" if "stock_code" in daily.c else "ts_code"
        date_col = "trade_date"
        if date_col not in daily.c:
            raise ValidationError("日线缺少 trade_date", details={"code": "BACKTEST_DAILY_SCHEMA"})

        raw_rows: list[dict[str, Any]] = []
        for batch in self._batches(codes):
            q = select(daily).where(
                and_(
                    daily.c[code_col].in_(batch),
                    daily.c[date_col] >= start,
                    daily.c[date_col] <= end,
                )
            )
            for r in (await session.execute(q)).mappings().all():
                raw_rows.append(dict(r))

        if not raw_rows:
            return {}

        adj_on: dict[tuple[str, date], float] = {}
        adj_latest: dict[str, float] = {}
        if adjust and adjust != "none":
            adj_on, adj_latest = await self._load_adj_maps(session, codes, start, end)

        by_code: dict[str, list[dict[str, Any]]] = {}
        for row in raw_rows:
            code = str(row.get(code_col) or row.get("stock_code") or "")
            td = row.get(date_col)
            if hasattr(td, "date"):
                td = td.date()
            elif isinstance(td, str):
                td = date.fromisoformat(td[:10])
            if not isinstance(td, date):
                continue
            item: dict[str, Any] = {"date": td, "volume": row.get("vol") or row.get("volume")}
            af = adj_on.get((code, td))
            latest = adj_latest.get(code)
            for k in OHLC_KEYS:
                raw = row.get(k)
                item[k] = apply_adjust(raw, adjust, af, latest)
            by_code.setdefault(code, []).append(item)

        frames: dict[str, pd.DataFrame] = {}
        for code, rows in by_code.items():
            df = pd.DataFrame(rows).sort_values("date").drop_duplicates("date", keep="last")
            df = df.dropna(subset=["open", "close"])
            if "open" in df.columns and "close" in df.columns:
                df = df[(df["open"] > 0) & (df["close"] > 0)]
            if not df.empty:
                frames[code] = df.reset_index(drop=True)
        return frames

    async def _load_adj_maps(
        self,
        session: AsyncSession,
        codes: list[str],
        start: date,
        end: date,
    ) -> tuple[dict[tuple[str, date], float], dict[str, float]]:
        adj_entry = get_data_type_entry("tushare_adj_factor")
        if not adj_entry or not adj_entry.table_name:
            return {}, {}
        table = await self._reflect(session, adj_entry.table_name)
        if table is None or "adj_factor" not in table.c:
            return {}, {}
        code_col = "stock_code" if "stock_code" in table.c else "ts_code"
        date_col = "trade_date" if "trade_date" in table.c else None
        if not date_col:
            return {}, {}

        on_date: dict[tuple[str, date], float] = {}
        last_by_code: dict[str, tuple[date, float]] = {}
        for batch in self._batches(codes):
            q = select(table).where(
                and_(
                    table.c[code_col].in_(batch),
                    table.c[date_col] >= start,
                    table.c[date_col] <= end,
                )
            )
            for r in (await session.execute(q)).mappings().all():
                d = dict(r)
                code = str(d.get(code_col))
                td = d.get(date_col)
                if hasattr(td, "date"):
                    td = td.date()
                elif isinstance(td, str):
                    td = date.fromisoformat(td[:10])
                try:
                    af = float(d["adj_factor"])
                except (TypeError, ValueError, KeyError):
                    continue
                if not isinstance(td, date):
                    continue
                on_date[(code, td)] = af
                prev = last_by_code.get(code)
                if prev is None or td > prev[0]:
                    last_by_code[code] = (td, af)

        # True latest adj_factor per code (for qfq), via max(trade_date) join — not full scan
        from sqlalchemy import func

        for batch in self._batches(codes):
            subq = (
                select(
                    table.c[code_col].label("c"),
                    func.max(table.c[date_col]).label("max_d"),
                )
                .where(table.c[code_col].in_(batch))
                .group_by(table.c[code_col])
                .subquery()
            )
            q2 = select(table).join(
                subq,
                and_(
                    table.c[code_col] == subq.c.c,
                    table.c[date_col] == subq.c.max_d,
                ),
            )
            for r in (await session.execute(q2)).mappings().all():
                d = dict(r)
                code = str(d.get(code_col))
                td = d.get(date_col)
                if hasattr(td, "date"):
                    td = td.date()
                elif isinstance(td, str):
                    td = date.fromisoformat(td[:10])
                try:
                    af = float(d["adj_factor"])
                except (TypeError, ValueError, KeyError):
                    continue
                if isinstance(td, date):
                    last_by_code[code] = (td, af)

        latest = {c: v[1] for c, v in last_by_code.items()}
        return on_date, latest

    async def _reflect(self, session: AsyncSession, table_name: str) -> Table | None:
        try:
            bind = await session.connection()
            metadata = MetaData()

            def _load(sync_conn):  # type: ignore[no-untyped-def]
                return Table(table_name, metadata, autoload_with=sync_conn)

            return await bind.run_sync(_load)
        except Exception:
            return None

    @staticmethod
    def _batches(codes: list[str], size: int = 200) -> list[list[str]]:
        return [codes[i : i + size] for i in range(0, len(codes), size)]
