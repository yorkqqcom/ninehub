"""Resolve universe specs to stock_code lists."""

from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import MetaData, Table, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.registry import get_data_type_entry
from app.schemas.query_browser import UniverseCustom, UniversePreset, UniverseSpec, UniverseWatchlist
from app.models.browser import BrowserWatchlist

SPINE_DATA_TYPE = "tushare_stock_basic"
MARGIN_DATA_TYPE = "tushare_margin_secs"
MAX_UNIVERSE = 8000
PREVIEW_TIMEOUT_SEC = 2.0

_A_SHARE_MARKETS = ("主板", "创业板", "科创板", "北交所")

_INDEX_PRESET_CODES: dict[str, str] = {
    "000300.SH": "399300.SZ",
    "399300.SZ": "399300.SZ",
    "000905.SH": "000905.SH",
}

_count_cache: dict[str, tuple[int, float]] = {}


class UniverseResolver:
    async def resolve(
        self,
        session: AsyncSession,
        universe: UniverseSpec,
        user_id: int | None = None,
        limit: int = MAX_UNIVERSE,
    ) -> list[str]:
        codes = await self._resolve_raw(session, universe, user_id)
        if not codes:
            return []
        if len(codes) > limit:
            return codes[:limit]
        return codes

    async def preview(
        self,
        session: AsyncSession,
        universe: UniverseSpec,
        user_id: int | None = None,
    ) -> tuple[int, list[str], list[str], bool]:
        warnings: list[str] = []
        is_estimate = False
        if isinstance(universe, UniversePreset) and (
            universe.preset in ("all_ab", "all_a", "all_b")
            or universe.preset.startswith(("exchange:", "market:"))
        ):
            count = await self._cached_preset_count(session, universe.preset)
            codes = await self.resolve(session, universe, user_id, limit=5)
            return count, codes, warnings, False
        if isinstance(universe, UniverseCustom):
            count = len(universe.codes)
            sample = universe.codes[:5]
            if count > MAX_UNIVERSE:
                warnings.append(f"超过上限 {MAX_UNIVERSE}，将截断")
            return min(count, MAX_UNIVERSE), sample, warnings, False
        try:
            codes = await asyncio.wait_for(
                self._resolve_raw(session, universe, user_id),
                timeout=PREVIEW_TIMEOUT_SEC,
            )
            count = len(codes)
            if count > MAX_UNIVERSE:
                warnings.append(f"超过上限 {MAX_UNIVERSE}，将截断")
                count = MAX_UNIVERSE
            return count, codes[:5], warnings, False
        except asyncio.TimeoutError:
            is_estimate = True
            warnings.append("计数超时，显示估算值")
            return 3000, [], warnings, is_estimate

    async def _cached_preset_count(self, session: AsyncSession, preset: str) -> int:
        cache_key = f"preset:{preset}"
        import time

        now = time.time()
        if cache_key in _count_cache and now - _count_cache[cache_key][1] < 3600:
            return _count_cache[cache_key][0]
        codes = await self._resolve_raw(session, UniversePreset(preset=preset), None)
        _count_cache[cache_key] = (len(codes), now)
        return len(codes)

    async def _resolve_raw(
        self,
        session: AsyncSession,
        universe: UniverseSpec,
        user_id: int | None,
    ) -> list[str]:
        if isinstance(universe, UniverseCustom):
            return [c.strip() for c in universe.codes if c.strip()]
        if isinstance(universe, UniverseWatchlist):
            row = await session.get(BrowserWatchlist, universe.watchlist_id)
            if row is None or (user_id and row.user_id != user_id):
                return []
            return list(row.codes_json or [])
        if isinstance(universe, UniversePreset):
            preset = universe.preset
            if preset in ("all_ab", "all_a", "all_b"):
                return await self._from_stock_basic(session, preset)
            if preset.startswith("exchange:"):
                suffix = preset.split(":", 1)[1]
                return await self._from_stock_basic(session, preset, exchange_suffix=suffix)
            if preset.startswith("market:"):
                board = preset.split(":", 1)[1]
                return await self._from_stock_basic(session, preset, market=board)
            if preset.startswith("industry:"):
                industry = preset.split(":", 1)[1]
                return await self._from_stock_basic(session, preset, industry=industry)
            if preset == "margin:eligible":
                return await self._from_margin_secs(session)
            if preset.startswith("index:"):
                index_code = preset.split(":", 1)[1]
                return await self._from_index_preset(session, index_code)
            if preset.startswith("sw:"):
                return await self._from_sw(session, preset)
        return []

    async def _spine_table(self, session: AsyncSession) -> Table | None:
        entry = get_data_type_entry(SPINE_DATA_TYPE)
        if not entry or not entry.table_name:
            return None
        conn = await session.connection()

        def _load(sync_conn) -> Table:
            metadata = MetaData()
            return Table(entry.table_name, metadata, autoload_with=sync_conn)

        try:
            return await conn.run_sync(_load)
        except Exception:
            return None

    async def _from_stock_basic(
        self,
        session: AsyncSession,
        preset: str,
        *,
        exchange_suffix: str | None = None,
        market: str | None = None,
        industry: str | None = None,
    ) -> list[str]:
        table = await self._spine_table(session)
        if table is None:
            return []
        code_col = "stock_code" if "stock_code" in table.c else "ts_code"
        q = select(table.c[code_col])
        if preset == "all_a" and "market" in table.c:
            q = q.where(table.c.market.in_(_A_SHARE_MARKETS))
        elif preset == "all_b":
            if "market" in table.c:
                q = q.where(table.c.market.like("%B%"))
            else:
                q = q.where(table.c[code_col].like("900%"))
        elif exchange_suffix:
            q = q.where(table.c[code_col].like(f"%.{exchange_suffix}"))
        elif market and "market" in table.c:
            q = q.where(table.c.market == market)
        elif industry and "industry" in table.c:
            q = q.where(table.c.industry == industry)
        rows = (await session.execute(q)).scalars().all()
        return [str(r) for r in rows if r]

    async def _from_margin_secs(self, session: AsyncSession) -> list[str]:
        entry = get_data_type_entry(MARGIN_DATA_TYPE)
        if not entry or not entry.table_name:
            return []
        conn = await session.connection()

        def _load(sync_conn) -> Table:
            metadata = MetaData()
            return Table(entry.table_name, metadata, autoload_with=sync_conn)

        try:
            table = await conn.run_sync(_load)
        except Exception:
            return []
        code_col = "stock_code" if "stock_code" in table.c else "ts_code"
        q = select(table.c[code_col]).distinct()
        rows = (await session.execute(q)).scalars().all()
        return [str(r) for r in rows if r]

    async def _from_index_preset(self, session: AsyncSession, preset_code: str) -> list[str]:
        api_code = _INDEX_PRESET_CODES.get(preset_code, preset_code)
        codes = await self._from_index_weight(session, api_code)
        if codes:
            return codes
        return await self._from_index_member(session, api_code)

    async def _from_index_weight(self, session: AsyncSession, index_code: str) -> list[str]:
        from sqlalchemy import text

        entry = get_data_type_entry("tushare_index_weight")
        if not entry or not entry.table_name:
            return []
        table = entry.table_name
        try:
            rows = await session.execute(
                text(
                    f"""
                    SELECT DISTINCT COALESCE(con_code, stock_code) AS code
                    FROM "{table}"
                    WHERE index_code = :idx
                      AND trade_date = (
                        SELECT MAX(trade_date) FROM "{table}" WHERE index_code = :idx
                      )
                    """
                ),
                {"idx": index_code},
            )
            return [str(r[0]) for r in rows.fetchall() if r[0]]
        except Exception:
            return []

    async def _from_index_member(self, session: AsyncSession, index_code: str) -> list[str]:
        entry = get_data_type_entry("tushare_index_member")
        if not entry or not entry.table_name:
            return []
        conn = await session.connection()

        def _load(sync_conn) -> Table:
            metadata = MetaData()
            return Table(entry.table_name, metadata, autoload_with=sync_conn)

        try:
            table = await conn.run_sync(_load)
        except Exception:
            return []
        code_col = "stock_code" if "stock_code" in table.c else "con_code"
        if code_col not in table.c and "ts_code" in table.c:
            code_col = "ts_code"
        idx_col = "index_code" if "index_code" in table.c else None
        q = select(table.c[code_col])
        if idx_col:
            q = q.where(table.c[idx_col] == index_code)
        rows = (await session.execute(q)).scalars().all()
        return [str(r) for r in rows if r]

    async def _from_sw(self, session: AsyncSession, preset: str) -> list[str]:
        entry = get_data_type_entry("tushare_index_member_all")
        if not entry or not entry.table_name:
            return []
        conn = await session.connection()

        def _load(sync_conn) -> Table:
            metadata = MetaData()
            return Table(entry.table_name, metadata, autoload_with=sync_conn)

        try:
            table = await conn.run_sync(_load)
        except Exception:
            return []
        parts = preset.split(":")
        sw_code = parts[-1] if len(parts) >= 3 else ""
        code_col = "stock_code" if "stock_code" in table.c else "ts_code"
        q = select(table.c[code_col])
        # preset sw:L1:801010.SI — match index_code / l1_code columns
        for col_name in ("l1_code", "l2_code", "l3_code", "index_code"):
            if col_name in table.c and sw_code:
                q = q.where(table.c[col_name] == sw_code)
                break
        rows = (await session.execute(q)).scalars().all()
        return [str(r) for r in rows if r]
