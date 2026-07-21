"""Batch realtime quotes via pytdx get_security_quotes (SH/SZ + 880 index)."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.tdx_sidecar.pytdx_gate import pytdx_slot
from app.tdx_sidecar.pytdx_hosts import host_list, remember_good_host
from app.tdx_sidecar.paths import merge_paths_config, resolve_effective_paths
from app.tdx_sidecar.security_names import lookup_stock_name

logger = logging.getLogger(__name__)

_BATCH_SIZE = 80
_SYMBOL_RE = re.compile(r"^(\d{6})\.(SH|SZ)$", re.IGNORECASE)
_INDEX_RE = re.compile(r"^880\d{3}$")


def normalize_symbol(raw: str) -> str | None:
    text = str(raw or "").strip().upper()
    m = _SYMBOL_RE.match(text)
    if not m:
        return None
    return f"{m.group(1)}.{m.group(2)}"


def normalize_index_code(raw: str) -> str | None:
    text = str(raw or "").strip().upper()
    if text.endswith(".TDX"):
        text = text[: -len(".TDX")]
    if _INDEX_RE.match(text):
        return text
    return None


def symbol_to_tdx(symbol: str) -> tuple[int, str] | None:
    sym = normalize_symbol(symbol)
    if not sym:
        return None
    code, market = sym.split(".", 1)
    if market == "SH":
        return 1, code
    if market == "SZ":
        return 0, code
    return None


def index_to_tdx(code: str) -> tuple[int, str] | None:
    idx = normalize_index_code(code)
    if not idx:
        return None
    return 1, idx


def _positive_float(val: Any) -> float | None:
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if f > 0 else None


def _row_to_symbol(row: dict[str, Any]) -> str | None:
    """Map pytdx quote row to 600000.SH / 000001.SZ when market+code present."""
    code = str(row.get("code") or "").strip()
    if not code.isdigit():
        return None
    code = code.zfill(6)
    try:
        market = int(row.get("market"))
    except (TypeError, ValueError):
        return None
    if market == 1:
        return f"{code}.SH"
    if market == 0:
        return f"{code}.SZ"
    return None


def _parse_row(symbol: str, row: dict[str, Any], *, ts_ms: int) -> dict[str, Any]:
    price = None
    for key in ("price", "last", "close"):
        price = _positive_float(row.get(key))
        if price is not None:
            break
    if price is None:
        try:
            rb = abs(int(row.get("reversed_bytes1") or 0))
            if rb > 0:
                price = rb / 100.0
        except (TypeError, ValueError):
            pass
    pre = None
    for key in ("last_close", "pre_close", "prev_close"):
        pre = _positive_float(row.get(key))
        if pre is not None:
            break
    open_px = _positive_float(row.get("open"))
    high = _positive_float(row.get("high"))
    low = _positive_float(row.get("low"))
    vol_raw = row.get("vol") if row.get("vol") is not None else row.get("volume")
    try:
        volume = float(vol_raw) if vol_raw is not None else None
    except (TypeError, ValueError):
        volume = None
    try:
        amount = float(row.get("amount")) if row.get("amount") is not None else None
    except (TypeError, ValueError):
        amount = None
    change_pct = None
    if pre and price and pre > 0:
        change_pct = (price - pre) / pre * 100.0
    name = str(row.get("name") or "").strip() or lookup_stock_name(symbol)
    return {
        "symbol": symbol,
        "name": name,
        "last_price": price,
        "pre_close": pre,
        "open": open_px,
        "high": high,
        "low": low,
        "volume": volume,
        "amount": amount,
        "change_pct": change_pct,
        "ts_ms": ts_ms,
        "degraded": price is None or price <= 0,
    }


def _host_list(connect_cfg_path: str | None) -> list[tuple[str, int]]:
    return host_list(connect_cfg_path)


def _security_quotes_resilient(api: Any, pairs: list[tuple[int, str]]) -> list[Any]:
    """Fetch quotes; bisect when a poison code makes the whole batch return None/[].

    Some HQ hosts return None for the entire request if any code is unsupported
    (e.g. delisted). Splitting isolates the bad code so peers still price.
    """
    if not pairs:
        return []
    raw = api.get_security_quotes(pairs)
    if raw:
        return list(raw)
    if len(pairs) == 1:
        return []
    mid = len(pairs) // 2
    return _security_quotes_resilient(api, pairs[:mid]) + _security_quotes_resilient(
        api, pairs[mid:]
    )


def fetch_quotes_batch(
    symbols: list[str],
    *,
    connect_cfg_path: str | None = None,
) -> dict[str, Any]:
    """Return {items, degraded, message, active_host}."""
    try:
        from pytdx.hq import TdxHq_API
    except ImportError:
        return {
            "items": [],
            "degraded": True,
            "message": "pytdx not installed; pip install -e '.[tdx]'",
            "active_host": "",
        }

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        sym = normalize_symbol(raw)
        if sym and sym not in seen:
            seen.add(sym)
            cleaned.append(sym)
    if len(cleaned) > 100:
        cleaned = cleaned[:100]

    if not cleaned:
        return {"items": [], "degraded": False, "message": "", "active_host": ""}

    if not connect_cfg_path:
        cfg = merge_paths_config()
        eff = resolve_effective_paths(cfg)
        connect_cfg_path = eff.connect_cfg_path

    pairs: list[tuple[int, str]] = []
    symbol_by_pair: dict[tuple[int, str], str] = {}
    for sym in cleaned:
        tdx = symbol_to_tdx(sym)
        if tdx:
            pairs.append(tdx)
            symbol_by_pair[tdx] = sym

    api = TdxHq_API(raise_exception=False)
    last_error = ""
    active_host = ""
    rows: list[Any] | None = None
    with pytdx_slot(2.5) as got:
        if not got:
            ts_ms = int(time.time() * 1000)
            return {
                "items": [
                    {
                        "symbol": s,
                        "name": lookup_stock_name(s),
                        "last_price": None,
                        "degraded": True,
                        "ts_ms": ts_ms,
                    }
                    for s in cleaned
                ],
                "degraded": True,
                "message": "pytdx busy",
                "active_host": "",
            }
        for host, port in _host_list(connect_cfg_path):
            try:
                if not api.connect(host, port, time_out=1.5):
                    last_error = f"connect failed {host}:{port}"
                    continue
                active_host = f"{host}:{port}"
                all_rows: list[Any] = []
                for i in range(0, len(pairs), _BATCH_SIZE):
                    all_rows.extend(_security_quotes_resilient(api, pairs[i : i + _BATCH_SIZE]))
                if not all_rows:
                    last_error = f"empty quotes {host}:{port}"
                    continue
                rows = all_rows
                remember_good_host(host, port)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.warning("pytdx quotes host %s:%s failed: %s", host, port, exc)
            finally:
                try:
                    api.disconnect()
                except Exception:  # noqa: BLE001
                    pass

    ts_ms = int(time.time() * 1000)
    if rows is None:
        return {
            "items": [
                {
                    "symbol": s,
                    "name": lookup_stock_name(s),
                    "last_price": None,
                    "degraded": True,
                    "ts_ms": ts_ms,
                }
                for s in cleaned
            ],
            "degraded": True,
            "message": last_error or "all pytdx hosts failed",
            "active_host": active_host,
        }

    by_sym: dict[str, dict[str, Any]] = {}
    wanted_syms = set(cleaned)
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        sym = _row_to_symbol(row)
        if sym is None or sym not in wanted_syms:
            # Fallback: positional match when host omits market/code
            pair = pairs[i] if i < len(pairs) else None
            sym = symbol_by_pair.get(pair) if pair is not None else None
        if sym and sym in wanted_syms:
            by_sym[sym] = _parse_row(sym, row, ts_ms=ts_ms)

    items = []
    for sym in cleaned:
        if sym in by_sym:
            items.append(by_sym[sym])
        else:
            items.append(
                {
                    "symbol": sym,
                    "name": lookup_stock_name(sym),
                    "last_price": None,
                    "degraded": True,
                    "ts_ms": ts_ms,
                }
            )

    any_ok = any(not bool(it.get("degraded")) for it in items)
    return {
        "items": items,
        "degraded": not any_ok,
        "message": "" if any_ok else (last_error or "no valid quotes"),
        "active_host": active_host,
    }


def fetch_index_quotes_batch(
    index_codes: list[str],
    *,
    connect_cfg_path: str | None = None,
) -> dict[str, Any]:
    """Batch quotes for TDX concept indices (880xxx). Returns items keyed by bare code."""
    try:
        from pytdx.hq import TdxHq_API
    except ImportError:
        return {"items": [], "degraded": True, "message": "pytdx not installed", "active_host": ""}

    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in index_codes:
        code = normalize_index_code(raw)
        if code and code not in seen:
            seen.add(code)
            cleaned.append(code)
    if len(cleaned) > 100:
        cleaned = cleaned[:100]
    if not cleaned:
        return {"items": [], "degraded": False, "message": "", "active_host": ""}

    if not connect_cfg_path:
        cfg = merge_paths_config()
        eff = resolve_effective_paths(cfg)
        connect_cfg_path = eff.connect_cfg_path

    pairs: list[tuple[int, str]] = [(1, c) for c in cleaned]
    api = TdxHq_API(raise_exception=False)
    last_error = ""
    active_host = ""
    rows: list[Any] | None = None
    with pytdx_slot(3.0) as got:
        if not got:
            ts_ms = int(time.time() * 1000)
            return {
                "items": [
                    {"code": c, "last_price": None, "degraded": True, "ts_ms": ts_ms}
                    for c in cleaned
                ],
                "degraded": True,
                "message": "pytdx busy",
                "active_host": "",
            }
        for host, port in _host_list(connect_cfg_path):
            try:
                if not api.connect(host, port, time_out=1.5):
                    last_error = f"connect failed {host}:{port}"
                    continue
                active_host = f"{host}:{port}"
                all_rows: list[Any] = []
                for i in range(0, len(pairs), _BATCH_SIZE):
                    all_rows.extend(_security_quotes_resilient(api, pairs[i : i + _BATCH_SIZE]))
                got_codes = {
                    str(row.get("code") or "").zfill(6)
                    for row in all_rows
                    if isinstance(row, dict) and row.get("code")
                }
                # 缺码，或 SH 行价为 0/无效：用深市市场号再试（与 get_index_bars 一致）
                need_sz: list[str] = [c for c in cleaned if c not in got_codes]
                for row in all_rows:
                    if not isinstance(row, dict):
                        continue
                    code = str(row.get("code") or "").zfill(6)
                    if code not in seen:
                        continue
                    priced = False
                    for key in ("price", "last", "close"):
                        if _positive_float(row.get(key)) is not None:
                            priced = True
                            break
                    if not priced and code not in need_sz:
                        need_sz.append(code)
                if need_sz:
                    miss_pairs = [(0, c) for c in need_sz]
                    for i in range(0, len(miss_pairs), _BATCH_SIZE):
                        all_rows.extend(
                            _security_quotes_resilient(api, miss_pairs[i : i + _BATCH_SIZE])
                        )
                if not all_rows:
                    last_error = f"empty index quotes {host}:{port}"
                    continue
                rows = all_rows
                remember_good_host(host, port)
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                logger.warning("pytdx index quotes host %s:%s failed: %s", host, port, exc)
            finally:
                try:
                    api.disconnect()
                except Exception:  # noqa: BLE001
                    pass

    ts_ms = int(time.time() * 1000)
    if rows is None:
        return {
            "items": [{"code": c, "last_price": None, "degraded": True, "ts_ms": ts_ms} for c in cleaned],
            "degraded": True,
            "message": last_error or "all pytdx hosts failed",
            "active_host": active_host,
        }

    by_code: dict[str, dict[str, Any]] = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        code = str(row.get("code") or "").zfill(6)
        if code not in seen:
            if i < len(pairs):
                code = pairs[i][1]
            else:
                continue
        parsed = _parse_row(code, row, ts_ms=ts_ms)
        parsed["code"] = code
        prev = by_code.get(code)
        # 同码多市场：保留有价的一帧
        if prev is None or (
            prev.get("last_price") is None and parsed.get("last_price") is not None
        ):
            by_code[code] = parsed

    items = []
    for code in cleaned:
        if code in by_code:
            items.append(by_code[code])
        else:
            items.append({"code": code, "symbol": code, "last_price": None, "degraded": True, "ts_ms": ts_ms})

    any_ok = any(not bool(it.get("degraded")) for it in items)
    return {
        "items": items,
        "degraded": not any_ok,
        "message": "" if any_ok else (last_error or "no valid index quotes"),
        "active_host": active_host,
    }
