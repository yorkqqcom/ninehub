"""pytdx index/stock short bars for rank speed (5m)."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.tdx_sidecar.pytdx_gate import pytdx_slot
from app.tdx_sidecar.pytdx_hosts import host_list
from app.tdx_sidecar.paths import merge_paths_config, resolve_effective_paths
from app.tdx_sidecar.quotes import normalize_symbol, symbol_to_tdx

logger = logging.getLogger(__name__)

_INDEX_RE = re.compile(r"^880\d{3}$")
# pytdx get_index_bars / get_security_bars category for 5m
_CAT_5M = 0


def normalize_index_code(raw: str) -> str | None:
    text = str(raw or "").strip().upper()
    if text.endswith(".TDX"):
        text = text[: -len(".TDX")]
    if _INDEX_RE.match(text):
        return text
    return None


def _host_list(connect_cfg_path: str | None) -> list[tuple[str, int]]:
    return host_list(connect_cfg_path)


def _bar_close(row: dict[str, Any]) -> float | None:
    for key in ("close", "price", "last"):
        try:
            v = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if v > 0:
            return v
    return None


def _speed_from_bars(bars: list[dict[str, Any]]) -> float | None:
    """Expect newest-first bars; speed = (latest - prev) / prev * 100."""
    if len(bars) < 2:
        return None
    latest = _bar_close(bars[0])
    prev = _bar_close(bars[1])
    if latest is None or prev is None or prev <= 0:
        return None
    return (latest - prev) / prev * 100.0


def fetch_index_5m_speed(
    index_code: str,
    *,
    connect_cfg_path: str | None = None,
) -> float | None:
    code = normalize_index_code(index_code)
    if not code:
        return None
    try:
        from pytdx.hq import TdxHq_API
    except ImportError:
        return None

    if not connect_cfg_path:
        eff = resolve_effective_paths(merge_paths_config())
        connect_cfg_path = eff.connect_cfg_path

    api = TdxHq_API(raise_exception=False)
    with pytdx_slot(2.0) as got:
        if not got:
            return None
        for host, port in _host_list(connect_cfg_path):
            try:
                if not api.connect(host, port, time_out=2):
                    continue
                for market in (1, 0):
                    rows = api.get_index_bars(_CAT_5M, market, code, 0, 4) or []
                    bars = [dict(r) for r in rows if isinstance(r, dict)]
                    # pytdx index bars are usually oldest-first; speed helper wants newest-first
                    if len(bars) >= 2:
                        bars = list(reversed(bars))
                    speed = _speed_from_bars(bars)
                    if speed is not None:
                        return speed
            except Exception as exc:  # noqa: BLE001
                logger.debug("index 5m bars %s failed: %s", code, exc)
            finally:
                try:
                    api.disconnect()
                except Exception:  # noqa: BLE001
                    pass
    return None


def fetch_stock_5m_speed(
    symbol: str,
    *,
    connect_cfg_path: str | None = None,
) -> float | None:
    sym = normalize_symbol(symbol)
    tdx = symbol_to_tdx(sym or "")
    if not tdx:
        return None
    try:
        from pytdx.hq import TdxHq_API
    except ImportError:
        return None

    if not connect_cfg_path:
        eff = resolve_effective_paths(merge_paths_config())
        connect_cfg_path = eff.connect_cfg_path

    market, code = tdx
    api = TdxHq_API(raise_exception=False)
    with pytdx_slot(2.0) as got:
        if not got:
            return None
        for host, port in _host_list(connect_cfg_path):
            try:
                if not api.connect(host, port, time_out=2):
                    continue
                rows = api.get_security_bars(_CAT_5M, market, code, 0, 4) or []
                bars = [dict(r) for r in rows if isinstance(r, dict)]
                # security bars usually oldest-first
                if len(bars) >= 2:
                    bars = list(reversed(bars))
                return _speed_from_bars(bars)
            except Exception as exc:  # noqa: BLE001
                logger.debug("stock 5m bars %s failed: %s", sym, exc)
            finally:
                try:
                    api.disconnect()
                except Exception:  # noqa: BLE001
                    pass
    return None
