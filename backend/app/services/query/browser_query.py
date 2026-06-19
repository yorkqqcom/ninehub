"""Data Browser wide-table query service."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from sqlalchemy import MetaData, Table, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.registry import get_data_type_entry
from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.schemas.query_browser import (
    BrowserAggregation,
    BrowserColumnMeta,
    BrowserExecuteMeta,
    BrowserExecuteRequest,
    BrowserExecuteResponse,
    BrowserSort,
    BrowserWarning,
)
from app.services.query.adj_price import apply_adjust
from app.services.query.browser_audit import BrowserAuditLogger, QueryTimer
from app.services.query.browser_cache import BrowserQueryCache
from app.services.query.indicator_registry import IndicatorRegistry
from app.services.query.universe_resolver import MAX_UNIVERSE, SPINE_DATA_TYPE, UniverseResolver
from app.services.trading_calendar.service import TradingCalendarService

MAX_INDICATORS_SOFT = 20
MAX_INDICATORS_HARD = 40
OHLC_KEYS = frozenset({"open", "high", "low", "close"})
CODE_BATCH_SIZE = 500


class BrowserQueryService:
    def __init__(self) -> None:
        self._indicators = IndicatorRegistry()
        self._universe = UniverseResolver()
        self._calendar = TradingCalendarService()
        self._audit = BrowserAuditLogger()
        self._cache = BrowserQueryCache()

    def _cache_key(self, request: BrowserExecuteRequest, user_id: int | None) -> str:
        payload = request.model_dump(
            mode="json",
            exclude={"skip", "limit", "include_aggregations", "force_refresh"},
        )
        if user_id is not None:
            payload["user_id"] = user_id
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    async def execute(
        self,
        session: AsyncSession,
        request: BrowserExecuteRequest,
        user_id: int | None = None,
    ) -> BrowserExecuteResponse:
        cache_key = self._cache_key(request, user_id)
        if not request.force_refresh:
            cached = self._cache.get(cache_key)
            if cached:
                return self._response_from_cache(cached, request)

        if request.dates:
            full = await self._execute_multi_date(session, request, user_id)
        else:
            full = await self._execute_single_date(session, request, user_id)

        ttl = get_settings().browser_query_cache_ttl
        self._cache.set(cache_key, full.model_dump(mode="json"), ttl_sec=ttl)
        return self._paginate(full, request)

    def _paginate(
        self, full: BrowserExecuteResponse, request: BrowserExecuteRequest
    ) -> BrowserExecuteResponse:
        page_items = full.items[request.skip : request.skip + request.limit]
        return BrowserExecuteResponse(
            items=page_items,
            total=full.total,
            page=request.skip // request.limit + 1 if request.limit else 1,
            size=request.limit,
            columns=full.columns,
            meta=full.meta,
            aggregations=full.aggregations if request.include_aggregations else [],
            warnings=full.warnings,
            code=full.code,
            cache_hit=False,
        )


    def _response_from_cache(
        self, cached: dict[str, Any], request: BrowserExecuteRequest
    ) -> BrowserExecuteResponse:
        full = BrowserExecuteResponse.model_validate(cached)
        page_items = full.items[request.skip : request.skip + request.limit]
        return BrowserExecuteResponse(
            items=page_items,
            total=full.total,
            page=request.skip // request.limit + 1 if request.limit else 1,
            size=request.limit,
            columns=full.columns,
            meta=full.meta,
            aggregations=full.aggregations if request.include_aggregations else [],
            warnings=full.warnings,
            code=full.code,
            cache_hit=True,
        )

    async def _execute_single_date(
        self,
        session: AsyncSession,
        request: BrowserExecuteRequest,
        user_id: int | None,
    ) -> BrowserExecuteResponse:
        timer = QueryTimer()
        warnings: list[BrowserWarning] = []
        refs = self._validate_indicators(request, warnings)

        codes = await self._universe.resolve(session, request.universe, user_id)
        self._validate_universe(codes)

        effective_date, date_adjusted = self._calendar.nearest_trading_day_on_or_before(
            request.as_of_date
        )

        daily_types_for_resolve = {r.data_type for _, r in refs if r.freq == "daily"}
        if daily_types_for_resolve:
            primary_dt = (
                "tushare_daily"
                if "tushare_daily" in daily_types_for_resolve
                else next(iter(daily_types_for_resolve))
            )
            primary_entry = get_data_type_entry(primary_dt)
            if primary_entry and primary_entry.table_name:
                resolved, data_adjusted, warn_msg = await self._resolve_daily_trade_date(
                    session, primary_entry.table_name, effective_date
                )
                if data_adjusted:
                    effective_date = resolved
                    date_adjusted = True
                if warn_msg:
                    warnings.append(BrowserWarning(reason=warn_msg))

        spine_entry = get_data_type_entry(SPINE_DATA_TYPE)
        if not spine_entry or not spine_entry.table_name:
            raise ValidationError("stock_basic 未激活", details={"code": "BROWSER_INDICATOR_UNAVAILABLE"})

        spine_by_code = await self._load_spine(session, spine_entry.table_name, codes)

        daily_types = {r.data_type for _, r in refs if r.freq == "daily"}
        period_types = {r.data_type for _, r in refs if r.freq == "period"}
        needs_adj = any(
            s.adjust and s.adjust != "none" and r.column_key in OHLC_KEYS for s, r in refs
        )

        daily_cache: dict[str, dict[str, dict[str, Any]]] = {}
        for dt in daily_types:
            entry = get_data_type_entry(dt)
            if entry and entry.table_name:
                daily_cache[dt] = await self._load_daily(
                    session, entry.table_name, codes, effective_date
                )
            else:
                warnings.append(BrowserWarning(indicator_id=dt, reason="日频表不可用"))

        period_cache: dict[str, dict[str, dict[str, Any]]] = {}
        for dt in period_types:
            entry = get_data_type_entry(dt)
            if entry and entry.table_name:
                period_cache[dt] = await self._load_period(
                    session,
                    entry.table_name,
                    codes,
                    request.as_of_date,
                    request.unified_end_date if request.financial_align == "unified" else None,
                )
            else:
                warnings.append(BrowserWarning(indicator_id=dt, reason="财报表不可用"))

        adj_factors: dict[str, float] = {}
        latest_adj: dict[str, float] = {}
        if needs_adj:
            adj_entry = get_data_type_entry("tushare_adj_factor")
            if adj_entry and adj_entry.table_name:
                adj_factors, latest_adj = await self._load_adj(
                    session, adj_entry.table_name, codes, effective_date
                )

        columns_meta: list[BrowserColumnMeta] = [
            BrowserColumnMeta(id="stock_code", label="交易代码", type="string"),
            BrowserColumnMeta(id="name", label="证券简称", type="string"),
        ]
        for sel, ref in refs:
            columns_meta.append(
                BrowserColumnMeta(
                    id=ref.id,
                    label=ref.label,
                    type=ref.type,
                    unit=ref.unit,
                    adjust=sel.adjust,
                    effective_date=effective_date.isoformat() if ref.freq == "daily" else None,
                )
            )

        static_types = {
            r.data_type for _, r in refs if r.freq == "static" and r.data_type != SPINE_DATA_TYPE
        }
        static_cache: dict[str, dict[str, dict[str, Any]]] = {}
        for dt in static_types:
            entry = get_data_type_entry(dt)
            if entry and entry.table_name:
                static_cache[dt] = await self._load_static_table(session, entry.table_name, codes)

        wide_rows = self._assemble_rows(
            codes,
            spine_by_code,
            refs,
            daily_cache,
            period_cache,
            static_cache,
            adj_factors,
            latest_adj,
            columns_meta,
        )

        return await self._finalize_response(
            session,
            request,
            user_id,
            wide_rows,
            columns_meta,
            warnings,
            timer,
            effective_date=effective_date,
            date_adjusted=date_adjusted,
            indicator_count=len(refs),
            universe_count=len(codes),
            multi_date_mode=False,
        )

    async def _execute_multi_date(
        self,
        session: AsyncSession,
        request: BrowserExecuteRequest,
        user_id: int | None,
    ) -> BrowserExecuteResponse:
        timer = QueryTimer()
        warnings: list[BrowserWarning] = []
        refs = self._validate_indicators(request, warnings)

        for _, ref in refs:
            if ref.freq == "period":
                raise ValidationError(
                    "多截面模式不支持期频指标",
                    details={"code": "BROWSER_MULTI_DATE_PERIOD"},
                )

        codes = await self._universe.resolve(session, request.universe, user_id)
        self._validate_universe(codes)

        snapshot_dates = list(request.dates or [])
        effective_dates: list[date] = []
        any_adjusted = False
        for d in snapshot_dates:
            ed, adjusted = self._calendar.nearest_trading_day_on_or_before(d)
            effective_dates.append(ed)
            any_adjusted = any_adjusted or adjusted

        spine_entry = get_data_type_entry(SPINE_DATA_TYPE)
        if not spine_entry or not spine_entry.table_name:
            raise ValidationError("stock_basic 未激活", details={"code": "BROWSER_INDICATOR_UNAVAILABLE"})

        spine_by_code = await self._load_spine(session, spine_entry.table_name, codes)

        daily_types = {r.data_type for _, r in refs if r.freq == "daily"}
        needs_adj = any(
            s.adjust and s.adjust != "none" and r.column_key in OHLC_KEYS for s, r in refs
        )

        daily_cache: dict[tuple[str, date], dict[str, dict[str, Any]]] = {}
        for dt in daily_types:
            entry = get_data_type_entry(dt)
            if not entry or not entry.table_name:
                warnings.append(BrowserWarning(indicator_id=dt, reason="日频表不可用"))
                continue
            for ed in set(effective_dates):
                daily_cache[(dt, ed)] = await self._load_daily(
                    session, entry.table_name, codes, ed
                )

        adj_by_date: dict[date, tuple[dict[str, float], dict[str, float]]] = {}
        if needs_adj:
            adj_entry = get_data_type_entry("tushare_adj_factor")
            if adj_entry and adj_entry.table_name:
                for ed in set(effective_dates):
                    adj_by_date[ed] = await self._load_adj(
                        session, adj_entry.table_name, codes, ed
                    )

        static_types = {
            r.data_type for _, r in refs if r.freq == "static" and r.data_type != SPINE_DATA_TYPE
        }
        static_cache: dict[str, dict[str, dict[str, Any]]] = {}
        for dt in static_types:
            entry = get_data_type_entry(dt)
            if entry and entry.table_name:
                static_cache[dt] = await self._load_static_table(session, entry.table_name, codes)

        columns_meta: list[BrowserColumnMeta] = [
            BrowserColumnMeta(id="stock_code", label="交易代码", type="string"),
            BrowserColumnMeta(id="name", label="证券简称", type="string"),
        ]
        col_specs: list[tuple[str, Any, Any, date | None]] = []
        for sel, ref in refs:
            if ref.freq == "daily":
                for ed in effective_dates:
                    col_id = f"{ref.id}@{ed.isoformat()}"
                    columns_meta.append(
                        BrowserColumnMeta(
                            id=col_id,
                            label=f"{ref.label} [{ed.isoformat()}]",
                            type=ref.type,
                            unit=ref.unit,
                            adjust=sel.adjust,
                            effective_date=ed.isoformat(),
                        )
                    )
                    col_specs.append(("daily", sel, ref, ed))
            else:
                columns_meta.append(
                    BrowserColumnMeta(
                        id=ref.id,
                        label=ref.label,
                        type=ref.type,
                        unit=ref.unit,
                        adjust=sel.adjust,
                    )
                )
                col_specs.append(("other", sel, ref, None))

        wide_rows: list[dict[str, Any]] = []
        for code in codes:
            spine = spine_by_code.get(code, {})
            row: dict[str, Any] = {
                "stock_code": code,
                "name": spine.get("name") or spine.get("stock_code") or code,
            }
            for kind, sel, ref, ed in col_specs:
                if kind == "daily" and ed is not None:
                    col_id = f"{ref.id}@{ed.isoformat()}"
                    dt_row = daily_cache.get((ref.data_type, ed), {}).get(code, {})
                    raw = dt_row.get(ref.column_key)
                    if ref.column_key in OHLC_KEYS and sel.adjust:
                        af, la = adj_by_date.get(ed, ({}, {}))
                        val = apply_adjust(raw, sel.adjust, af.get(code), la.get(code))
                    else:
                        val = raw
                    row[col_id] = val
                elif kind == "other":
                    if ref.freq == "static":
                        if ref.data_type == SPINE_DATA_TYPE:
                            row[ref.id] = spine.get(ref.column_key)
                        else:
                            row[ref.id] = static_cache.get(ref.data_type, {}).get(code, {}).get(
                                ref.column_key
                            )
            wide_rows.append(row)

        primary_ed = effective_dates[0] if effective_dates else request.as_of_date
        return await self._finalize_response(
            session,
            request,
            user_id,
            wide_rows,
            columns_meta,
            warnings,
            timer,
            effective_date=primary_ed,
            date_adjusted=any_adjusted,
            indicator_count=len(refs),
            universe_count=len(codes),
            multi_date_mode=True,
            effective_dates=[d.isoformat() for d in effective_dates],
        )

    def _validate_indicators(
        self, request: BrowserExecuteRequest, warnings: list[BrowserWarning]
    ) -> list[tuple[Any, Any]]:
        if len(request.indicators) > MAX_INDICATORS_HARD:
            raise ValidationError(
                f"指标数超过上限 {MAX_INDICATORS_HARD}",
                details={"code": "BROWSER_TOO_MANY_INDICATORS"},
            )
        if len(request.indicators) > MAX_INDICATORS_SOFT:
            warnings.append(
                BrowserWarning(
                    reason=f"指标数 {len(request.indicators)} 超过建议值 {MAX_INDICATORS_SOFT}"
                )
            )
        refs = []
        for sel in request.indicators:
            ref = self._indicators.get_indicator(sel.id)
            if ref is None:
                raise ValidationError(
                    f"未知指标: {sel.id}",
                    details={"code": "BROWSER_INDICATOR_UNAVAILABLE"},
                )
            if not ref.available:
                raise ValidationError(
                    f"指标未就绪: {sel.id}",
                    details={"code": "BROWSER_INDICATOR_UNAVAILABLE"},
                )
            refs.append((sel, ref))
        return refs

    def _validate_universe(self, codes: list[str]) -> None:
        if not codes:
            raise ValidationError("证券池为空", details={"code": "BROWSER_UNIVERSE_EMPTY"})
        if len(codes) > MAX_UNIVERSE:
            raise ValidationError(
                f"证券池超过 {MAX_UNIVERSE}",
                details={"code": "BROWSER_UNIVERSE_TOO_LARGE"},
            )

    def _assemble_rows(
        self,
        codes: list[str],
        spine_by_code: dict[str, dict[str, Any]],
        refs: list[tuple[Any, Any]],
        daily_cache: dict[str, dict[str, dict[str, Any]]],
        period_cache: dict[str, dict[str, dict[str, Any]]],
        static_cache: dict[str, dict[str, dict[str, Any]]],
        adj_factors: dict[str, float],
        latest_adj: dict[str, float],
        columns_meta: list[BrowserColumnMeta],
    ) -> list[dict[str, Any]]:
        wide_rows: list[dict[str, Any]] = []
        for code in codes:
            spine = spine_by_code.get(code, {})
            row: dict[str, Any] = {
                "stock_code": code,
                "name": spine.get("name") or spine.get("stock_code") or code,
            }
            for sel, ref in refs:
                val: Any = None
                if ref.freq == "static":
                    if ref.data_type == SPINE_DATA_TYPE:
                        val = spine.get(ref.column_key)
                    else:
                        val = static_cache.get(ref.data_type, {}).get(code, {}).get(ref.column_key)
                elif ref.freq == "daily":
                    dt_row = daily_cache.get(ref.data_type, {}).get(code, {})
                    raw = dt_row.get(ref.column_key)
                    if ref.column_key in OHLC_KEYS and sel.adjust:
                        val = apply_adjust(
                            raw,
                            sel.adjust,
                            adj_factors.get(code),
                            latest_adj.get(code),
                        )
                    else:
                        val = raw
                elif ref.freq == "period":
                    p_row = period_cache.get(ref.data_type, {}).get(code, {})
                    val = p_row.get(ref.column_key)
                    ed = p_row.get("end_date")
                    if ed and isinstance(ed, str):
                        for cm in columns_meta:
                            if cm.id == ref.id:
                                cm.effective_end_date = ed[:10]
                    elif ed and isinstance(ed, date):
                        for cm in columns_meta:
                            if cm.id == ref.id:
                                cm.effective_end_date = ed.isoformat()
                row[ref.id] = val
            wide_rows.append(row)
        return wide_rows

    def _warn_empty_indicator_columns(
        self,
        wide_rows: list[dict[str, Any]],
        columns_meta: list[BrowserColumnMeta],
        warnings: list[BrowserWarning],
    ) -> None:
        if not wide_rows:
            return
        existing = {w.indicator_id for w in warnings if w.indicator_id}
        for col in columns_meta:
            if col.id in ("stock_code", "name"):
                continue
            if col.id in existing:
                continue
            if any(r.get(col.id) is not None for r in wide_rows):
                continue
            warnings.append(
                BrowserWarning(
                    indicator_id=col.id,
                    reason=f"「{col.label}」在所选条件下无数据，请检查采集或调整截面/截止日",
                )
            )

    async def _finalize_response(
        self,
        session: AsyncSession,
        request: BrowserExecuteRequest,
        user_id: int | None,
        wide_rows: list[dict[str, Any]],
        columns_meta: list[BrowserColumnMeta],
        warnings: list[BrowserWarning],
        timer: QueryTimer,
        *,
        effective_date: date,
        date_adjusted: bool,
        indicator_count: int,
        universe_count: int,
        multi_date_mode: bool,
        effective_dates: list[str] | None = None,
    ) -> BrowserExecuteResponse:
        if request.sort:
            wide_rows = self._sort_rows(wide_rows, request.sort)
        total = len(wide_rows)

        sort_applied = request.sort
        col_ids = [c.id for c in columns_meta if c.id not in ("stock_code", "name")]
        aggregations: list[BrowserAggregation] = []
        if request.include_aggregations:
            aggregations = self._compute_aggregations(wide_rows, col_ids)

        self._warn_empty_indicator_columns(wide_rows, columns_meta, warnings)

        duration_ms = timer.elapsed_ms()
        self._audit.warn_slow(
            duration_ms,
            {"indicators": indicator_count, "universe": universe_count},
        )
        await self._audit.log_query(
            session,
            user_id,
            request.universe,
            [s.id for s in request.indicators],
            request.as_of_date.isoformat(),
            total,
            duration_ms,
        )

        code = "BROWSER_PARTIAL_DATA" if warnings else None
        return BrowserExecuteResponse(
            items=wide_rows,
            total=total,
            page=1,
            size=total,
            columns=columns_meta,
            meta=BrowserExecuteMeta(
                as_of_date=request.as_of_date.isoformat(),
                effective_date=effective_date.isoformat(),
                effective_dates=effective_dates or [effective_date.isoformat()],
                date_adjusted=date_adjusted,
                universe_count=universe_count,
                indicator_count=indicator_count,
                sort_applied=sort_applied,
                multi_date_mode=multi_date_mode,
            ),
            aggregations=aggregations,
            warnings=warnings,
            code=code,
            cache_hit=False,
        )

    async def _reflect(self, session: AsyncSession, table_name: str) -> Table | None:
        conn = await session.connection()

        def _load(sync_conn) -> Table:
            metadata = MetaData()
            return Table(table_name, metadata, autoload_with=sync_conn)

        try:
            return await conn.run_sync(_load)
        except Exception:
            return None

    async def _load_spine(
        self, session: AsyncSession, table_name: str, codes: list[str]
    ) -> dict[str, dict[str, Any]]:
        table = await self._reflect(session, table_name)
        if table is None:
            return {}
        code_col = "stock_code" if "stock_code" in table.c else "ts_code"
        out: dict[str, dict[str, Any]] = {}
        for batch in self._code_batches(codes):
            q = select(table).where(table.c[code_col].in_(batch))
            rows = (await session.execute(q)).mappings().all()
            for r in rows:
                d = dict(r)
                key = str(d.get(code_col) or d.get("stock_code") or d.get("ts_code"))
                out[key] = self._serialize(d)
        return out

    async def _load_static_table(
        self, session: AsyncSession, table_name: str, codes: list[str]
    ) -> dict[str, dict[str, Any]]:
        table = await self._reflect(session, table_name)
        if table is None:
            return {}
        code_col = "stock_code" if "stock_code" in table.c else "ts_code"
        out: dict[str, dict[str, Any]] = {}
        for batch in self._code_batches(codes):
            q = select(table).where(table.c[code_col].in_(batch))
            rows = (await session.execute(q)).mappings().all()
            for r in rows:
                d = self._serialize(dict(r))
                key = str(d.get(code_col) or d.get("stock_code"))
                out[key] = d
        return out

    async def _resolve_daily_trade_date(
        self,
        session: AsyncSession,
        table_name: str,
        requested: date,
    ) -> tuple[date, bool, str | None]:
        """Use requested date when rows exist; else fall back to latest trade_date <= requested."""
        table = await self._reflect(session, table_name)
        if table is None:
            return requested, False, None
        date_col = "trade_date" if "trade_date" in table.c else None
        if not date_col:
            return requested, False, None

        count_q = select(func.count()).select_from(table).where(table.c[date_col] == requested)
        count = int((await session.execute(count_q)).scalar_one() or 0)
        if count > 0:
            return requested, False, None

        max_q = select(func.max(table.c[date_col])).where(table.c[date_col] <= requested)
        max_date = (await session.execute(max_q)).scalar_one()
        if max_date is None:
            return requested, False, f"{requested.isoformat()} 及之前无日频数据"

        if hasattr(max_date, "date") and not isinstance(max_date, date):
            max_date = max_date.date()
        if max_date == requested:
            return requested, False, f"{requested.isoformat()} 无日频数据"

        return (
            max_date,
            True,
            f"截面日 {requested.isoformat()} 无日频数据，"
            f"已回退至最近可用交易日 {max_date.isoformat()}",
        )

    async def _load_daily(
        self,
        session: AsyncSession,
        table_name: str,
        codes: list[str],
        trade_date: date,
    ) -> dict[str, dict[str, Any]]:
        table = await self._reflect(session, table_name)
        if table is None:
            return {}
        code_col = "stock_code" if "stock_code" in table.c else "ts_code"
        date_col = "trade_date" if "trade_date" in table.c else None
        if not date_col:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for batch in self._code_batches(codes):
            q = select(table).where(
                and_(table.c[code_col].in_(batch), table.c[date_col] == trade_date)
            )
            rows = (await session.execute(q)).mappings().all()
            for r in rows:
                d = self._serialize(dict(r))
                key = str(d.get(code_col) or d.get("stock_code"))
                out[key] = d
        return out

    async def _load_period(
        self,
        session: AsyncSession,
        table_name: str,
        codes: list[str],
        as_of: date,
        unified_end: date | None,
    ) -> dict[str, dict[str, Any]]:
        table = await self._reflect(session, table_name)
        if table is None:
            return {}
        code_col = "stock_code" if "stock_code" in table.c else "ts_code"
        end_col = "end_date" if "end_date" in table.c else "ann_date"
        if end_col not in table.c:
            return {}
        best: dict[str, dict[str, Any]] = {}
        for batch in self._code_batches(codes):
            clauses = [table.c[code_col].in_(batch), table.c[end_col] <= as_of]
            if unified_end:
                clauses.append(table.c[end_col] == unified_end)
            q = select(table).where(and_(*clauses))
            rows = (await session.execute(q)).mappings().all()
            for r in rows:
                d = self._serialize(dict(r))
                key = str(d.get(code_col) or d.get("stock_code"))
                prev = best.get(key)
                if prev is None or str(d.get(end_col, "")) > str(prev.get(end_col, "")):
                    best[key] = d
        return best

    async def _load_adj(
        self,
        session: AsyncSession,
        table_name: str,
        codes: list[str],
        trade_date: date,
    ) -> tuple[dict[str, float], dict[str, float]]:
        table = await self._reflect(session, table_name)
        if table is None or "adj_factor" not in table.c:
            return {}, {}
        code_col = "stock_code" if "stock_code" in table.c else "ts_code"
        date_col = "trade_date" if "trade_date" in table.c else None
        on_date: dict[str, float] = {}
        if date_col:
            for batch in self._code_batches(codes):
                q = select(table).where(
                    and_(table.c[code_col].in_(batch), table.c[date_col] == trade_date)
                )
                for r in (await session.execute(q)).mappings().all():
                    d = dict(r)
                    key = str(d.get(code_col))
                    try:
                        on_date[key] = float(d["adj_factor"])
                    except (TypeError, ValueError, KeyError):
                        pass
        latest: dict[str, float] = {}
        for batch in self._code_batches(codes):
            subq = (
                select(code_col, func.max(table.c[date_col]).label("max_d"))
                .where(table.c[code_col].in_(batch))
                .group_by(table.c[code_col])
                .subquery()
            )
            if date_col:
                q2 = select(table).join(
                    subq,
                    and_(
                        table.c[code_col] == subq.c[code_col],
                        table.c[date_col] == subq.c.max_d,
                    ),
                )
                for r in (await session.execute(q2)).mappings().all():
                    d = dict(r)
                    key = str(d.get(code_col))
                    try:
                        latest[key] = float(d["adj_factor"])
                    except (TypeError, ValueError, KeyError):
                        pass
        return on_date, latest

    @staticmethod
    def _code_batches(codes: list[str]) -> list[list[str]]:
        return [codes[i : i + CODE_BATCH_SIZE] for i in range(0, len(codes), CODE_BATCH_SIZE)]

    def _sort_rows(self, rows: list[dict[str, Any]], sort: BrowserSort) -> list[dict[str, Any]]:
        col = sort.column

        def key_fn(r: dict[str, Any]) -> Any:
            v = r.get(col)
            if v is None:
                return (1, "")
            return (0, v)

        return sorted(rows, key=key_fn, reverse=(sort.direction == "desc"))

    def _compute_aggregations(
        self, rows: list[dict[str, Any]], col_ids: list[str]
    ) -> list[BrowserAggregation]:
        result: list[BrowserAggregation] = []
        for col_id in col_ids:
            nums: list[float] = []
            for r in rows:
                v = r.get(col_id)
                if v is None:
                    continue
                try:
                    nums.append(float(v))
                except (TypeError, ValueError):
                    continue
            if not nums:
                result.append(BrowserAggregation(column_id=col_id, count=0))
                continue
            result.append(
                BrowserAggregation(
                    column_id=col_id,
                    sum=sum(nums),
                    avg=sum(nums) / len(nums),
                    min=min(nums),
                    max=max(nums),
                    count=len(nums),
                )
            )
        return result

    def _serialize(self, row: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, val in row.items():
            if key in ("id", "created_at"):
                continue
            if hasattr(val, "isoformat"):
                out[key] = val.isoformat() if not isinstance(val, date) else val
            elif val is not None and hasattr(val, "__float__"):
                try:
                    out[key] = float(val)
                except (TypeError, ValueError):
                    out[key] = val
            else:
                out[key] = val
            if key == "ts_code" and "stock_code" not in out:
                out["stock_code"] = val
        return out
