"""Dimension registry — built-in universe presets grouped by category."""

from __future__ import annotations

import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.registry import get_data_type_entry
from app.schemas.query_browser import DimensionRef

CLASSIFY_DATA_TYPE = "tushare_index_classify"
MEMBER_DATA_TYPE = "tushare_index_member_all"
INDEX_MEMBER_DATA_TYPE = "tushare_index_member"
INDEX_WEIGHT_DATA_TYPE = "tushare_index_weight"

_INDEX_LABELS: dict[str, str] = {
    "399300.SZ": "沪深300",
    "000300.SH": "沪深300",
    "000905.SH": "中证500",
    "000016.SH": "上证50",
    "000852.SH": "中证1000",
    "399006.SZ": "创业板指",
    "000688.SH": "科创50",
}
_INDEX_PRESET_CODES: dict[str, str] = {
    "000300.SH": "399300.SZ",
    "399300.SZ": "399300.SZ",
    "000905.SH": "000905.SH",
}
SW_SRC = "SW2021"
_SW_L1_CACHE_TTL_SEC = 3600.0
_INDUSTRY_CACHE_TTL_SEC = 3600.0
_sw_l1_cache: dict[str, tuple[list[DimensionRef], float]] = {}
_industry_cache: tuple[list[DimensionRef], float] | None = None

_BUILTIN: list[DimensionRef] = [
    DimensionRef(id="all_ab", label="全部 AB 股", category="market", description="A股+B股"),
    DimensionRef(id="all_a", label="全部 A 股", category="market", description="主板+创业板+科创板+北交所"),
    DimensionRef(id="all_b", label="全部 B 股", category="market"),
    DimensionRef(id="exchange:SH", label="上交所", category="market", description="stock_code 后缀 .SH"),
    DimensionRef(id="exchange:SZ", label="深交所", category="market", description="stock_code 后缀 .SZ"),
    DimensionRef(id="exchange:BJ", label="北交所", category="market", description="stock_code 后缀 .BJ"),
    DimensionRef(id="market:主板", label="上证主板", category="market"),
    DimensionRef(id="market:创业板", label="创业板", category="market"),
    DimensionRef(id="market:科创板", label="科创板", category="market"),
    DimensionRef(id="market:北交所", label="北交所板块", category="market"),
    DimensionRef(
        id="margin:eligible",
        label="融资融券标的",
        category="special",
        description="margin_secs 表",
    ),
]

_CATEGORY_LABELS: dict[str, str] = {
    "market": "市场板块",
    "industry": "行业标准",
    "sw": "申万行业",
    "index": "指数/概念",
    "pool": "自定义板块",
    "special": "特色筛选",
}


class DimensionRegistry:
    def category_labels(self) -> dict[str, str]:
        return dict(_CATEGORY_LABELS)

    async def list_dimensions(self, session: AsyncSession | None = None) -> list[DimensionRef]:
        dims = [d.model_copy(update={"available": self._is_available(d)}) for d in _BUILTIN]
        if session is not None:
            dims.extend(await self._load_industry_presets(session))
            sw = await self._load_sw_l1_presets(session)
            if not sw:
                dims.append(
                    DimensionRef(
                        id="sw:placeholder",
                        label="申万行业（未就绪）",
                        category="sw",
                        available=False,
                        degraded=True,
                        description="需采集 index_classify + index_member_all",
                    )
                )
            else:
                dims.extend(sw)
            index_presets = await self._load_index_presets(session)
            if index_presets:
                dims.extend(index_presets)
            else:
                dims.extend(self._fallback_index_presets())
        return dims

    def _fallback_index_presets(self) -> list[DimensionRef]:
        return [
            DimensionRef(
                id="index:399300.SZ",
                label="沪深300成分",
                category="index",
                available=False,
                degraded=True,
                description="需采集 index_weight · 2000积分",
            ),
            DimensionRef(
                id="index:000905.SH",
                label="中证500成分",
                category="index",
                available=False,
                degraded=True,
                description="需采集 index_weight · 2000积分",
            ),
        ]

    async def _load_industry_presets(self, session: AsyncSession) -> list[DimensionRef]:
        global _industry_cache
        now = time.time()
        if _industry_cache and now - _industry_cache[1] < _INDUSTRY_CACHE_TTL_SEC:
            return _industry_cache[0]

        spine = get_data_type_entry("tushare_stock_basic")
        if not spine or not spine.table_name:
            return []

        try:
            rows = (
                await session.execute(
                    text(
                        f"""
                        SELECT industry, COUNT(*) AS cnt
                        FROM "{spine.table_name}"
                        WHERE industry IS NOT NULL AND industry != ''
                        GROUP BY industry
                        ORDER BY cnt DESC
                        """
                    )
                )
            ).fetchall()
        except Exception:
            return []

        presets: list[DimensionRef] = []
        for industry, cnt in rows:
            if not industry:
                continue
            name = str(industry).strip()
            count = int(cnt or 0)
            presets.append(
                DimensionRef(
                    id=f"industry:{name}",
                    label=name,
                    category="industry",
                    available=True,
                    stock_count=count,
                    description=f"{count} 只 · 证监会行业",
                )
            )
        _industry_cache = (presets, now)
        return presets

    async def _load_sw_l1_presets(self, session: AsyncSession) -> list[DimensionRef]:
        classify = get_data_type_entry(CLASSIFY_DATA_TYPE)
        member = get_data_type_entry(MEMBER_DATA_TYPE)
        if not classify or not classify.is_activated or not classify.table_name:
            return []
        if not member or not member.is_activated or not member.table_name:
            return []

        cache_key = f"{classify.table_name}:{member.table_name}"
        now = time.time()
        cached = _sw_l1_cache.get(cache_key)
        if cached and now - cached[1] < _SW_L1_CACHE_TTL_SEC:
            return cached[0]

        classify_table = classify.table_name
        member_table = member.table_name
        try:
            rows = (
                await session.execute(
                    text(
                        f"""
                        SELECT c.index_code, c.industry_name, COUNT(DISTINCT m.stock_code) AS cnt
                        FROM "{classify_table}" c
                        LEFT JOIN "{member_table}" m
                          ON m.l1_code = c.index_code
                         AND (m.is_new IS NULL OR m.is_new = 'Y')
                        WHERE c.level = 'L1' AND c.src = :src
                        GROUP BY c.index_code, c.industry_name
                        ORDER BY c.industry_name
                        """
                    ),
                    {"src": SW_SRC},
                )
            ).fetchall()
        except Exception:
            return []

        presets: list[DimensionRef] = []
        for index_code, industry_name, cnt in rows:
            if not index_code or not industry_name:
                continue
            code = str(index_code).strip()
            name = str(industry_name).strip()
            stock_count = int(cnt or 0)
            presets.append(
                DimensionRef(
                    id=f"sw:L1:{code}",
                    label=f"申万一级·{name}",
                    category="sw",
                    available=stock_count > 0,
                    degraded=stock_count == 0,
                    stock_count=stock_count,
                    description=f"{stock_count} 只 · {code}",
                )
            )

        _sw_l1_cache[cache_key] = (presets, now)
        return presets

    async def _load_index_presets(self, session: AsyncSession) -> list[DimensionRef]:
        weight = get_data_type_entry(INDEX_WEIGHT_DATA_TYPE)
        if not weight or not weight.is_activated or not weight.table_name:
            return []
        table = weight.table_name
        try:
            rows = (
                await session.execute(
                    text(
                        f"""
                        SELECT w.index_code,
                               COUNT(DISTINCT COALESCE(w.con_code, w.stock_code)) AS cnt
                        FROM "{table}" w
                        INNER JOIN (
                            SELECT index_code, MAX(trade_date) AS max_d
                            FROM "{table}"
                            GROUP BY index_code
                        ) latest ON w.index_code = latest.index_code
                                 AND w.trade_date = latest.max_d
                        GROUP BY w.index_code
                        HAVING COUNT(DISTINCT COALESCE(w.con_code, w.stock_code)) > 0
                        ORDER BY cnt DESC
                        """
                    )
                )
            ).fetchall()
        except Exception:
            return []

        presets: list[DimensionRef] = []
        seen: set[str] = set()
        for index_code, cnt in rows:
            if not index_code:
                continue
            code = str(index_code).strip()
            if code in seen:
                continue
            seen.add(code)
            count = int(cnt or 0)
            label = _INDEX_LABELS.get(code, f"指数·{code}")
            presets.append(
                DimensionRef(
                    id=f"index:{code}",
                    label=label,
                    category="index",
                    available=count > 0,
                    degraded=count == 0,
                    stock_count=count,
                    description=f"{count} 只 · {code}",
                )
            )
        return presets

    def _is_available(self, d: DimensionRef) -> bool:
        if d.id.startswith("index:"):
            weight = get_data_type_entry(INDEX_WEIGHT_DATA_TYPE)
            if weight and weight.is_activated:
                return True
            entry = get_data_type_entry(INDEX_MEMBER_DATA_TYPE)
            return bool(entry and entry.is_activated)
        if d.id.startswith("sw:"):
            entry = get_data_type_entry(MEMBER_DATA_TYPE)
            return bool(entry and entry.is_activated)
        if d.id == "margin:eligible":
            entry = get_data_type_entry("tushare_margin_secs")
            return bool(entry and entry.is_activated and entry.table_name)
        if d.id.startswith(("all_", "exchange:", "market:", "industry:")):
            spine = get_data_type_entry("tushare_stock_basic")
            return bool(spine and spine.is_activated)
        return d.available
