"""HTTP client for TDX Sidecar ranks / bars (Watch proxy)."""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_RANKS_TIMEOUT = 20.0
_BARS_TIMEOUT = 25.0
_DAY_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


class SidecarTransportError(Exception):
    """Sidecar unreachable / HTTP error — Watch should map to 502 so UI keeps last frame."""


class SidecarClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_token: str | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (
            base_url
            or settings.watch_tdx_sidecar_url
            or settings.tdx_sidecar_base_url
            or "http://127.0.0.1:8090"
        ).rstrip("/")
        self.api_token = (
            api_token or settings.watch_tdx_sidecar_token or settings.tdx_sidecar_api_token or ""
        )

    def _headers(self) -> dict[str, str]:
        if not self.api_token:
            return {}
        return {"Authorization": f"Bearer {self.api_token}"}

    def fetch_ranks_snapshot(
        self,
        *,
        pool_symbols: list[str],
        concept_code: str | None = None,
        top_n: int = 30,
    ) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=_RANKS_TIMEOUT) as client:
                resp = client.post(
                    f"{self.base_url}/api/v1/market/ranks/snapshot",
                    json={
                        "pool_symbols": pool_symbols,
                        "concept_code": concept_code,
                        "top_n": top_n,
                    },
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sidecar ranks snapshot failed: %s", exc)
            raise SidecarTransportError(str(exc)) from exc

        if not isinstance(data, dict):
            raise SidecarTransportError("invalid ranks payload")
        return data

    def fetch_bars(
        self,
        *,
        symbol: str,
        period: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=_BARS_TIMEOUT) as client:
                resp = client.post(
                    f"{self.base_url}/api/v1/market/bars/batch",
                    json={
                        "period": period,
                        "start_date": start_date.isoformat(),
                        "end_date": end_date.isoformat(),
                        "stock_codes": [symbol],
                    },
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Sidecar bars failed symbol=%s: %s", symbol, exc)
            raise SidecarTransportError(str(exc)) from exc

        if not isinstance(data, dict):
            raise SidecarTransportError("invalid bars payload")

        items_raw = data.get("items")
        items: list[dict[str, Any]] = []
        for row in items_raw or []:
            if not isinstance(row, dict):
                continue
            items.append(_normalize_bar_row(row))

        prev_close: float | None = None
        if period == "1m" and items:
            prev_close = _extract_prev_close(items)
            items = _crop_1m_last_session(items)

        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        message = str(data.get("message") or "")
        degraded = bool(data.get("degraded") or meta.get("degraded"))
        err = str(meta.get("error") or "")
        if not items and not message:
            if "connect" in err.lower():
                message = "行情主机连接失败"
                degraded = True
            elif _is_concept_index(symbol):
                message = "暂无概念分时" if period in {"1m", "5m"} else "暂无概念指数K线"
                degraded = True
            elif period in {"1m", "5m"}:
                message = "暂无分钟线（非交易日或无本地分钟线）"
                degraded = True
            else:
                message = "暂无 K 线数据"
                degraded = True
        elif not items and err and not degraded:
            degraded = True

        return {
            "items": items,
            "prev_close": prev_close,
            "degraded": degraded,
            "message": message,
            "meta": meta or {},
        }


def _is_concept_index(symbol: str) -> bool:
    text = str(symbol or "").strip().upper()
    if text.endswith(".TDX"):
        text = text[: -len(".TDX")]
    return bool(re.fullmatch(r"880\d{3}", text))


def _day_key(ts: Any) -> str | None:
    if ts is None:
        return None
    s = str(ts)[:10]
    return s if _DAY_KEY_RE.match(s) else None


def _extract_prev_close(items: list[dict[str, Any]]) -> float | None:
    """Last close of the trade day strictly before max day; None if only one day."""
    max_day: str | None = None
    for row in items:
        d = _day_key(row.get("ts"))
        if d and (max_day is None or d > max_day):
            max_day = d
    if max_day is None:
        return None
    prev_day: str | None = None
    for row in items:
        d = _day_key(row.get("ts"))
        if d and d < max_day and (prev_day is None or d > prev_day):
            prev_day = d
    if prev_day is None:
        return None
    last_close: float | None = None
    last_ts = ""
    for row in sorted(items, key=lambda r: str(r.get("ts") or "")):
        if _day_key(row.get("ts")) != prev_day:
            continue
        ts = str(row.get("ts") or "")
        c = _num(row.get("close"))
        if c is None:
            continue
        if ts >= last_ts:
            last_ts = ts
            last_close = c
    return last_close


def _crop_1m_last_session(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only the latest trade day for Watch 1m charts; preserve order by ts."""
    max_day: str | None = None
    for row in items:
        d = _day_key(row.get("ts"))
        if d and (max_day is None or d > max_day):
            max_day = d
    if max_day is None:
        return sorted(items, key=lambda r: str(r.get("ts") or ""))
    cropped = [r for r in items if _day_key(r.get("ts")) == max_day]
    return sorted(cropped, key=lambda r: str(r.get("ts") or ""))


def _normalize_bar_row(row: dict[str, Any]) -> dict[str, Any]:
    ts = (
        row.get("ts")
        or row.get("bar_time")
        or row.get("trade_date")
        or row.get("datetime")
        or row.get("time")
    )
    if hasattr(ts, "isoformat"):
        ts = ts.isoformat()
    return {
        "ts": ts,
        "open": _num(row.get("open")),
        "high": _num(row.get("high")),
        "low": _num(row.get("low")),
        "close": _num(row.get("close")),
        "volume": _num(row.get("volume") if row.get("volume") is not None else row.get("vol")),
        "amount": _num(row.get("amount")),
    }


def _num(val: Any) -> float | None:
    try:
        if val is None:
            return None
        f = float(val)
    except (TypeError, ValueError):
        return None
    # 丢弃 pytdx 浮点噪点，避免前端均价/成交量被污染
    if abs(f) < 1e-6:
        return 0.0
    return f


def bars_date_window(period: str, *, today: date | None = None) -> tuple[date, date]:
    """Choose start/end for Sidecar bars/batch."""
    end = today or date.today()
    if period == "1m":
        return end - timedelta(days=10), end
    if period == "1d":
        return end - timedelta(days=400), end
    return end - timedelta(days=30), end


_client: SidecarClient | None = None


def get_sidecar_client() -> SidecarClient:
    global _client
    if _client is None:
        _client = SidecarClient()
    return _client
