"""Slim market rank engine for Cockpit-style lanes (concept + watch pool)."""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any

from app.tdx_sidecar.cache import TtlLruCache
from app.tdx_sidecar.concept_catalog import export_concept_catalog
from app.tdx_sidecar.index_bars import fetch_index_5m_speed, fetch_stock_5m_speed, normalize_index_code
from app.tdx_sidecar.paths import merge_paths_config, resolve_effective_paths
from app.tdx_sidecar.quotes import fetch_index_quotes_batch, fetch_quotes_batch, normalize_symbol
from app.tdx_sidecar.security_names import set_stock_names

logger = logging.getLogger(__name__)

_BATCH_CONCEPTS = 10
_BATCH_SLEEP_MS = 200
_BATCH_CONCURRENCY = 1  # 串行占闸，避免与请求路径成分行情抢 pytdx
_ROUND_SLEEP_SEC = 5.0
_SERVING_TTL_SEC = 7.0
# 请求路径不打全市场；涨幅以 warm 缓存为主，TTL 内直出
_CHANGE_TTL_SEC = 20.0
_CHANGE_STALE_OK_SEC = 120.0
_STOCK_SPEED_BUDGET = 40
_WATCHDOG_SEC = 30.0
_TOP_N_DEFAULT = 30


def _pool_key(symbols: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(symbols)).encode("utf-8")).hexdigest()


def _sort_key(row: dict[str, Any], field: str) -> float:
    val = row.get(field)
    try:
        return float(val) if val is not None else -1e18
    except (TypeError, ValueError):
        return -1e18


def _rows_have_index_quotes(rows: list[dict[str, Any]] | None) -> bool:
    """涨幅缓存是否含可用指数价/涨幅（全 null 不得当命中，否则看板长期「—」）。"""
    if not rows:
        return False
    for row in rows:
        if row.get("change_pct") is not None:
            return True
        last = row.get("last")
        if last is not None:
            try:
                if float(last) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _connect_cfg_path() -> str | None:
    try:
        return resolve_effective_paths(merge_paths_config()).connect_cfg_path
    except Exception:  # noqa: BLE001
        return None


class RankEngine:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._round_in_progress = False
        self._progress = 0.0
        self._catalog_ok = False
        self._serving: list[dict[str, Any]] = []
        self._expires_at = 0.0
        self._change_cache: dict[str, Any] = {"ts": 0.0, "rows": [], "catalog_ok": False}
        self._stock_speed_cache: TtlLruCache[list[dict[str, Any]]] = TtlLruCache(maxsize=128, ttl=15.0)
        self._stock_speed_inflight: dict[str, threading.Event] = {}
        self._stock_speed_inflight_lock = threading.Lock()
        self._indices: list[dict[str, str]] = []
        self._members: dict[str, list[str]] = {}
        # 成分导出 txt 自带 stock_name；pytdx get_security_quotes 无名称字段
        self._stock_names: dict[str, str] = {}
        # 某概念无成分时最多强制重载一次，避免看板 4s 轮询反复解析全量目录
        self._constituent_reload_tried: set[str] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._warm_loop, name="concept-speed-warm", daemon=False)
        self._thread.start()
        logger.info("concept speed warm thread started")

    def bootstrap_catalog(self) -> bool:
        """启动时预载目录与股票名称缓存（不依赖 warm 线程）。"""
        ok = self._load_catalog()
        logger.info("rank catalog bootstrap ok=%s names=%s", ok, len(self._stock_names))
        return ok

    def stop(self, *, join_timeout: float = 2.0) -> None:
        self._stop.set()
        t = self._thread
        if t and t.is_alive():
            t.join(timeout=join_timeout)
        self._thread = None

    def _load_catalog(self) -> bool:
        try:
            eff = resolve_effective_paths(merge_paths_config())
            payload = export_concept_catalog(
                hq_cache_root=eff.hq_cache_root,
                concept_export_dir=eff.concept_export_dir,
                trade_date=date.today(),
            )
            indices_raw = payload.get("concept_index") or []
            members_raw = payload.get("concept_member") or []
            indices: list[dict[str, str]] = []
            for row in indices_raw:
                if not isinstance(row, dict):
                    continue
                code = normalize_index_code(str(row.get("index_code") or ""))
                name = str(row.get("name") or code or "")
                if code:
                    indices.append({"code": code, "name": name})
            members: dict[str, list[str]] = {}
            stock_names: dict[str, str] = {}
            for row in members_raw:
                if not isinstance(row, dict):
                    continue
                code = normalize_index_code(str(row.get("index_code") or ""))
                stock = normalize_symbol(str(row.get("stock_code") or ""))
                if not code or not stock:
                    continue
                bucket = members.setdefault(code, [])
                if stock not in bucket:
                    bucket.append(stock)
                sn = str(row.get("stock_name") or "").strip()
                if sn and stock not in stock_names:
                    stock_names[stock] = sn
            with self._lock:
                self._indices = indices
                self._members = members
                self._stock_names = stock_names
                self._catalog_ok = bool(indices)
            set_stock_names(stock_names)
            logger.info(
                "concept catalog loaded indices=%s members_codes=%s member_rows=%s source=%s",
                len(indices),
                len(members),
                sum(len(v) for v in members.values()),
                payload.get("concept_member_source"),
            )
            return bool(indices)
        except Exception as exc:  # noqa: BLE001
            logger.warning("load concept catalog failed: %s", exc)
            # 保留上一份目录，避免瞬时失败把已有 serving/成分一起打空
            with self._lock:
                self._catalog_ok = bool(self._indices)
            return bool(self._indices)

    def _resolve_stock_name(self, symbol: str, quote_name: str | None = None) -> str:
        """pytdx quotes 无 name；优先 quote，其次目录导出 / 全局缓存。"""
        from app.tdx_sidecar.security_names import lookup_stock_name

        n = str(quote_name or "").strip()
        if n:
            return n
        sym = str(symbol or "").strip().upper()
        with self._lock:
            local = str(self._stock_names.get(sym) or self._stock_names.get(symbol) or "")
        return local or lookup_stock_name(sym)

    def _warm_loop(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            try:
                self._run_warm_round()
            except Exception as exc:  # noqa: BLE001
                logger.warning("concept speed warm round failed: %s", exc)
                with self._lock:
                    self._round_in_progress = False
            elapsed = time.time() - started
            if elapsed > _WATCHDOG_SEC:
                logger.warning("concept speed warm slow elapsed=%.1fs", elapsed)
            # 轮间续租：serving 有效时把 TTL 推过 sleep，避免轮间 ~2s 空窗 speed_warm 误灭
            with self._lock:
                if self._serving:
                    self._expires_at = max(self._expires_at, time.time() + _SERVING_TTL_SEC)
            # sleep 5s between rounds (interruptible)
            if self._stop.wait(_ROUND_SLEEP_SEC):
                break

    def _publish_change_cache(
        self, indices: list[dict[str, str]], change_by_code: dict[str, dict[str, Any]]
    ) -> None:
        change_rows: list[dict[str, Any]] = []
        for item in indices:
            code = item["code"]
            qq = change_by_code.get(code) or {}
            change_rows.append(
                {
                    "code": code,
                    "name": item["name"],
                    "change_pct": qq.get("change_pct"),
                    "last": qq.get("last_price"),
                }
            )
        change_rows.sort(key=lambda r: _sort_key(r, "change_pct"), reverse=True)
        for rank, row in enumerate(change_rows, start=1):
            row["rank"] = rank
        with self._lock:
            self._change_cache = {
                "ts": time.time(),
                "rows": change_rows,
                "catalog_ok": True,
            }

    def _run_warm_round(self) -> None:
        with self._lock:
            self._round_in_progress = True
            if self._serving:
                self._expires_at = max(self._expires_at, time.time() + _SERVING_TTL_SEC)
            self._progress = 0.0
        ok = self._load_catalog()
        with self._lock:
            indices = list(self._indices)
        if not ok or not indices:
            with self._lock:
                self._progress = 1.0
                self._round_in_progress = False
            return

        cfg_path = _connect_cfg_path()
        total = len(indices)
        change_by_code: dict[str, dict[str, Any]] = {}

        # Phase A：先批量拉指数涨幅并增量写入缓存（请求路径已不再冷拉行情）
        for i in range(0, total, _BATCH_CONCEPTS):
            if self._stop.is_set():
                with self._lock:
                    self._round_in_progress = False
                return
            chunk = indices[i : i + _BATCH_CONCEPTS]
            try:
                q = fetch_index_quotes_batch(
                    [item["code"] for item in chunk],
                    connect_cfg_path=cfg_path,
                )
                for it in q.get("items") or []:
                    if not isinstance(it, dict):
                        continue
                    code = str(it.get("code") or "")
                    if code:
                        change_by_code[code] = it
            except Exception as exc:  # noqa: BLE001
                logger.debug("warm index quotes chunk failed: %s", exc)
            self._publish_change_cache(indices, change_by_code)
            with self._lock:
                self._progress = 0.35 * ((i + len(chunk)) / float(total))
            if i + _BATCH_CONCEPTS < total:
                time.sleep(_BATCH_SLEEP_MS / 1000.0)

        # Phase B：5m 涨速（较慢，不阻塞涨幅车道）
        building: list[dict[str, Any]] = []
        for i in range(0, total, _BATCH_CONCEPTS):
            if self._stop.is_set():
                with self._lock:
                    self._round_in_progress = False
                return
            chunk = indices[i : i + _BATCH_CONCEPTS]
            speeds: dict[str, float | None] = {}
            with ThreadPoolExecutor(max_workers=_BATCH_CONCURRENCY) as pool:
                futs = {
                    pool.submit(fetch_index_5m_speed, item["code"]): item["code"] for item in chunk
                }
                for fut in as_completed(futs):
                    code = futs[fut]
                    try:
                        speeds[code] = fut.result()
                    except Exception:  # noqa: BLE001
                        speeds[code] = None
            for item in chunk:
                code = item["code"]
                qq = change_by_code.get(code) or {}
                building.append(
                    {
                        "code": code,
                        "name": item["name"],
                        "speed_pct": speeds.get(code),
                        "change_pct": qq.get("change_pct"),
                        "last": qq.get("last_price"),
                    }
                )
            done = i + len(chunk)
            with self._lock:
                self._progress = 0.35 + 0.65 * (done / float(total))
                # 轮中续租，避免长时间 5m 拉取导致 speed_warm 误灭
                if building:
                    partial = list(building)
                    partial.sort(key=lambda r: _sort_key(r, "speed_pct"), reverse=True)
                    for rank, row in enumerate(partial, start=1):
                        row["rank"] = rank
                    self._serving = partial
                    self._expires_at = time.time() + _SERVING_TTL_SEC
            if i + _BATCH_CONCEPTS < total:
                time.sleep(_BATCH_SLEEP_MS / 1000.0)

        building.sort(key=lambda r: _sort_key(r, "speed_pct"), reverse=True)
        for rank, row in enumerate(building, start=1):
            row["rank"] = rank

        self._publish_change_cache(indices, change_by_code)
        with self._lock:
            self._serving = building
            self._expires_at = time.time() + _SERVING_TTL_SEC
            self._progress = 1.0
            self._round_in_progress = False
        logger.info(
            "concept speed warm done n=%s change_quoted=%s",
            len(building),
            len(change_by_code),
        )

    def _speed_meta(self) -> tuple[bool, bool, float]:
        """Align plan: speed_warm/stale_speed depend on serving, not catalog_ok."""
        now = time.time()
        with self._lock:
            serving = list(self._serving)
            expires_at = self._expires_at
            in_prog = self._round_in_progress
            progress = float(self._progress)
        nonempty = bool(serving)
        speed_warm = nonempty and (now < expires_at or in_prog)
        stale_speed = nonempty and now >= expires_at and in_prog
        if not in_prog and nonempty and now < expires_at:
            progress = 1.0
        elif not nonempty:
            progress = progress if in_prog else 0.0
        return speed_warm, stale_speed, progress

    def _fetch_concepts_change_budget(
        self, indices: list[dict[str, str]], top_n: int
    ) -> list[dict[str, Any]]:
        """请求路径拉一小批指数涨幅（warm 关闭或缓存全空时的兜底）。"""
        budget = indices[: min(len(indices), 40)]
        q = fetch_index_quotes_batch(
            [i["code"] for i in budget],
            connect_cfg_path=_connect_cfg_path(),
        )
        by_code = {
            str(it.get("code") or ""): it
            for it in (q.get("items") or [])
            if isinstance(it, dict)
        }
        rows: list[dict[str, Any]] = []
        for item in budget:
            code = item["code"]
            qq = by_code.get(code) or {}
            rows.append(
                {
                    "code": code,
                    "name": item["name"],
                    "change_pct": qq.get("change_pct"),
                    "last": qq.get("last_price"),
                }
            )
        rows.sort(key=lambda r: _sort_key(r, "change_pct"), reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        if _rows_have_index_quotes(rows):
            with self._lock:
                self._change_cache = {"ts": time.time(), "rows": rows, "catalog_ok": True}
        return rows[:top_n]

    def _concepts_change(self, top_n: int) -> tuple[list[dict[str, Any]], bool]:
        """概念涨幅：优先 warm 缓存；全 null 缓存不当命中，避免看板涨幅永久「—」。"""
        now = time.time()
        with self._lock:
            cached = self._change_cache
            age = now - float(cached.get("ts") or 0)
            rows_cached = cached.get("rows")
            catalog_ok = bool(cached.get("catalog_ok") or self._catalog_ok)
            indices = list(self._indices)
            cached_list = list(rows_cached) if isinstance(rows_cached, list) else []
            usable = _rows_have_index_quotes(cached_list)
            if usable and age < _CHANGE_TTL_SEC:
                return cached_list[:top_n], catalog_ok
            # 过期但仍在宽限内：直接返回旧帧，由 warm 后台刷新
            if usable and age < _CHANGE_STALE_OK_SEC:
                return cached_list[:top_n], catalog_ok

        if not indices:
            if not self._load_catalog():
                return [], False
            with self._lock:
                indices = list(self._indices)
                catalog_ok = self._catalog_ok
                rows_cached = self._change_cache.get("rows")
                cached_list = list(rows_cached) if isinstance(rows_cached, list) else []
        if not indices:
            return [], False

        warm_alive = bool(self._thread and self._thread.is_alive())
        with self._lock:
            in_prog = self._round_in_progress
        # warm 未启动：请求路径兜底
        # warm 已结束但仍是全 null 缓存：兜底（进行中不抢闸，避免与 Phase A/B 争用）
        published_empty = bool(cached_list) and not _rows_have_index_quotes(cached_list)
        if (not warm_alive) or (published_empty and not in_prog):
            return self._fetch_concepts_change_budget(indices, top_n), True

        # 冷启动 / warm 进行中：仅目录骨架（可点选概念看成分）
        rows: list[dict[str, Any]] = [
            {
                "code": item["code"],
                "name": item["name"],
                "change_pct": None,
                "last": None,
            }
            for item in indices
        ]
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return rows[:top_n], True

    def _enrich_concept_lanes(
        self,
        change_rows: list[dict[str, Any]],
        speed_rows: list[dict[str, Any]],
    ) -> None:
        """交叉填充指数/涨幅/涨速，供前端统一列展示。"""
        with self._lock:
            speed_all = list(self._serving)
            change_all = list(self._change_cache.get("rows") or [])
        by_speed = {str(r.get("code") or ""): r for r in speed_all if r.get("code")}
        by_change = {str(r.get("code") or ""): r for r in change_all if r.get("code")}
        for row in change_rows:
            code = str(row.get("code") or "")
            src = by_speed.get(code) or {}
            if row.get("speed_pct") is None and src.get("speed_pct") is not None:
                row["speed_pct"] = src.get("speed_pct")
            if row.get("last") is None and src.get("last") is not None:
                row["last"] = src.get("last")
            if row.get("change_pct") is None and src.get("change_pct") is not None:
                row["change_pct"] = src.get("change_pct")
        for row in speed_rows:
            code = str(row.get("code") or "")
            src = by_change.get(code) or {}
            if row.get("change_pct") is None and src.get("change_pct") is not None:
                row["change_pct"] = src.get("change_pct")
            if row.get("last") is None and src.get("last") is not None:
                row["last"] = src.get("last")
            if row.get("speed_pct") is None and src.get("speed_pct") is not None:
                row["speed_pct"] = src.get("speed_pct")

    def _enrich_stock_lanes(
        self,
        change_rows: list[dict[str, Any]],
        speed_rows: list[dict[str, Any]],
        *,
        pool: list[str] | None = None,
    ) -> None:
        """交叉填充最新价/涨幅/涨速/名称，供前端统一列展示。

        涨速车道按 speed 排序后只取 top_n，需合并缓存全量，避免涨幅榜股票漏 speed_pct。
        """
        by_speed: dict[str, dict[str, Any]] = {
            str(r.get("symbol") or ""): r for r in speed_rows if r.get("symbol")
        }
        by_change: dict[str, dict[str, Any]] = {
            str(r.get("symbol") or ""): r for r in change_rows if r.get("symbol")
        }
        if pool:
            cached = self._stock_speed_cache.get(_pool_key(pool))
            if cached:
                for r in cached:
                    sym = str(r.get("symbol") or "")
                    if not sym:
                        continue
                    if sym not in by_speed:
                        by_speed[sym] = r
                        continue
                    # 同标的：用缓存补全 top_n 行里仍为空的字段
                    dst = by_speed[sym]
                    if dst is r:
                        continue
                    for key in ("speed_pct", "last", "change_pct"):
                        if dst.get(key) is None and r.get(key) is not None:
                            dst[key] = r.get(key)
                    if not str(dst.get("name") or "").strip() and str(r.get("name") or "").strip():
                        dst["name"] = r.get("name")
        for row in change_rows:
            sym = str(row.get("symbol") or "")
            src = by_speed.get(sym) or {}
            if row.get("speed_pct") is None and src.get("speed_pct") is not None:
                row["speed_pct"] = src.get("speed_pct")
            if row.get("last") is None and src.get("last") is not None:
                row["last"] = src.get("last")
            if row.get("change_pct") is None and src.get("change_pct") is not None:
                row["change_pct"] = src.get("change_pct")
            if not str(row.get("name") or "").strip() and src.get("name"):
                row["name"] = src.get("name")
        for row in speed_rows:
            sym = str(row.get("symbol") or "")
            src = by_change.get(sym) or {}
            if row.get("change_pct") is None and src.get("change_pct") is not None:
                row["change_pct"] = src.get("change_pct")
            if row.get("last") is None and src.get("last") is not None:
                row["last"] = src.get("last")
            if row.get("speed_pct") is None and src.get("speed_pct") is not None:
                row["speed_pct"] = src.get("speed_pct")
            if not str(row.get("name") or "").strip() and src.get("name"):
                row["name"] = src.get("name")

    def _stocks_change(self, pool: list[str], top_n: int) -> list[dict[str, Any]]:
        if not pool:
            return []
        q = fetch_quotes_batch(pool, connect_cfg_path=_connect_cfg_path())
        rows: list[dict[str, Any]] = []
        for it in q.get("items") or []:
            if not isinstance(it, dict):
                continue
            sym = str(it.get("symbol") or "")
            if not sym:
                continue
            rows.append(
                {
                    "symbol": sym,
                    "name": self._resolve_stock_name(sym, str(it.get("name") or "")),
                    "change_pct": it.get("change_pct"),
                    "last": it.get("last_price"),
                }
            )
        rows.sort(key=lambda r: _sort_key(r, "change_pct"), reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        return rows[:top_n]

    def _stocks_speed(self, pool: list[str], top_n: int) -> list[dict[str, Any]]:
        if not pool:
            return []
        key = _pool_key(pool)
        hit = self._stock_speed_cache.get(key)
        if hit is not None:
            return hit[:top_n]

        with self._stock_speed_inflight_lock:
            ev = self._stock_speed_inflight.get(key)
            if ev is None:
                ev = threading.Event()
                self._stock_speed_inflight[key] = ev
                owner = True
            else:
                owner = False

        if not owner:
            ev.wait(timeout=20.0)
            hit2 = self._stock_speed_cache.get(key)
            return (hit2 or [])[:top_n]

        try:
            budget = pool[: min(len(pool), _STOCK_SPEED_BUDGET)]
            speeds: dict[str, float | None] = {}
            with ThreadPoolExecutor(max_workers=_BATCH_CONCURRENCY) as pool_ex:
                futs = {pool_ex.submit(fetch_stock_5m_speed, s): s for s in budget}
                for fut in as_completed(futs):
                    sym = futs[fut]
                    try:
                        speeds[sym] = fut.result()
                    except Exception:  # noqa: BLE001
                        speeds[sym] = None
            q = fetch_quotes_batch(budget, connect_cfg_path=_connect_cfg_path())
            by_quote: dict[str, dict[str, Any]] = {}
            for it in q.get("items") or []:
                if not isinstance(it, dict):
                    continue
                sym = str(it.get("symbol") or "")
                if sym:
                    by_quote[sym] = it
            rows = []
            for s in budget:
                qq = by_quote.get(s) or {}
                rows.append(
                    {
                        "symbol": s,
                        "name": self._resolve_stock_name(s, str(qq.get("name") or "")),
                        "speed_pct": speeds.get(s),
                        "change_pct": qq.get("change_pct"),
                        "last": qq.get("last_price"),
                    }
                )
            rows.sort(key=lambda r: _sort_key(r, "speed_pct"), reverse=True)
            for rank, row in enumerate(rows, start=1):
                row["rank"] = rank
            self._stock_speed_cache.set(key, rows)
            return rows[:top_n]
        finally:
            ev.set()
            with self._stock_speed_inflight_lock:
                self._stock_speed_inflight.pop(key, None)

    def _constituents(
        self, concept_code: str | None, top_n: int
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        code = normalize_index_code(concept_code or "")
        empty_meta = {"member_count": 0, "quote_count": 0, "reason": "no_members"}
        if not code:
            return [], {**empty_meta, "reason": "no_concept"}
        with self._lock:
            stocks = list(self._members.get(code) or [])
            already_tried = code in self._constituent_reload_tried
            if not stocks and not already_tried:
                self._constituent_reload_tried.add(code)
                should_reload = True
            else:
                should_reload = False
        if should_reload:
            self._load_catalog()
            with self._lock:
                stocks = list(self._members.get(code) or [])
        member_count = len(stocks)
        if not stocks:
            return [], {**empty_meta, "member_count": 0, "reason": "no_members"}
        stocks = stocks[:100]
        cfg_path = _connect_cfg_path()
        quote_by_sym: dict[str, dict[str, Any]] = {}
        # 行情失败时最多再试 1 次；锁忙或已有部分价则不再拖时间
        for _attempt in range(2):
            q = fetch_quotes_batch(stocks, connect_cfg_path=cfg_path)
            quote_by_sym = {}
            for it in q.get("items") or []:
                if not isinstance(it, dict):
                    continue
                sym = str(it.get("symbol") or "")
                if sym:
                    quote_by_sym[sym] = it
            if any(
                isinstance(v, dict) and v.get("last_price") is not None for v in quote_by_sym.values()
            ):
                break
            msg = str(q.get("message") or "")
            if msg == "pytdx busy":
                break
            time.sleep(0.1)

        rows: list[dict[str, Any]] = []
        for sym in stocks:
            it = quote_by_sym.get(sym) or {}
            rows.append(
                {
                    "symbol": sym,
                    "name": self._resolve_stock_name(sym, str(it.get("name") or "")),
                    "change_pct": it.get("change_pct"),
                    "last": it.get("last_price"),
                }
            )
        rows.sort(key=lambda r: _sort_key(r, "change_pct"), reverse=True)
        for rank, row in enumerate(rows, start=1):
            row["rank"] = rank
        # quote_count 统计全部成分有价数（非 top_n 切片），便于 UI 展示覆盖率
        usable = sum(1 for r in rows if r.get("last") is not None)
        reason = "ok" if usable else "no_quotes"
        return rows[:top_n], {
            "member_count": member_count,
            "quote_count": usable,
            "reason": reason,
        }

    def snapshot(
        self,
        *,
        pool_symbols: list[str] | None = None,
        concept_code: str | None = None,
        top_n: int = _TOP_N_DEFAULT,
    ) -> dict[str, Any]:
        top_n = max(1, min(int(top_n or _TOP_N_DEFAULT), 30))
        pool: list[str] = []
        seen: set[str] = set()
        for raw in pool_symbols or []:
            sym = normalize_symbol(str(raw))
            if sym and sym not in seen:
                seen.add(sym)
                pool.append(sym)

        # 先解析 active 并拉成分行情，避免 _concepts_change 全量指数报价占满线路后成分失败
        active = normalize_index_code(concept_code or "")
        if active:
            with self._lock:
                known = {i["code"] for i in self._indices}
            if not known:
                self._load_catalog()
                with self._lock:
                    known = {i["code"] for i in self._indices}
            if known and active not in known:
                active = None

        constituents, constituents_meta = self._constituents(active, top_n)

        concepts_change, catalog_ok = self._concepts_change(top_n)
        speed_warm, stale_speed, progress = self._speed_meta()
        with self._lock:
            serving = list(self._serving)[:top_n]
            catalog_ok = catalog_ok or self._catalog_ok
        self._enrich_concept_lanes(concepts_change, serving)

        stocks_change = self._stocks_change(pool, top_n)
        stocks_speed = self._stocks_speed(pool, top_n)
        self._enrich_stock_lanes(stocks_change, stocks_speed, pool=pool)

        degraded = False
        message = ""
        if not catalog_ok:
            message = "concept catalog unavailable"
            degraded = True

        return {
            "concepts_change": concepts_change,
            "concepts_speed": serving,
            "stocks_change": stocks_change,
            "stocks_speed": stocks_speed,
            "constituents": constituents,
            "constituents_meta": constituents_meta,
            "active_concept": active,
            "degraded": degraded,
            "message": message,
            "meta": {
                "catalog_ok": catalog_ok,
                "speed_warm": speed_warm,
                "speed_warm_progress": progress if catalog_ok else 1.0,
                "pool_count": len(pool),
                "stale_speed": stale_speed,
            },
        }


_engine: RankEngine | None = None
_engine_lock = threading.Lock()


def get_rank_engine() -> RankEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = RankEngine()
        return _engine
