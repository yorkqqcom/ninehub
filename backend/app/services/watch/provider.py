"""QuoteProvider protocol and TdxSidecar implementation."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.core.config import get_settings
from app.services.watch.types import QuoteBatch, snap_from_dict

logger = logging.getLogger(__name__)


class QuoteProvider(Protocol):
    def get_quotes(self, symbols: list[str]) -> QuoteBatch: ...


class TdxSidecarQuoteProvider:
    def __init__(
        self,
        base_url: str | None = None,
        api_token: str | None = None,
        *,
        timeout: float = 5.0,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.watch_tdx_sidecar_url or settings.tdx_sidecar_base_url or "http://127.0.0.1:8090").rstrip("/")
        self.api_token = api_token or settings.watch_tdx_sidecar_token or settings.tdx_sidecar_api_token or ""
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self.api_token:
            return {}
        return {"Authorization": f"Bearer {self.api_token}"}

    def get_quotes(self, symbols: list[str]) -> QuoteBatch:
        if not symbols:
            return QuoteBatch()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/api/v1/market/quotes",
                    json={"symbols": symbols},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TdxSidecarQuoteProvider failed: %s", exc)
            return QuoteBatch(degraded=True, message=str(exc))

        items = {}
        for row in data.get("items") or []:
            if not isinstance(row, dict):
                continue
            snap = snap_from_dict(row)
            if snap.symbol:
                items[snap.symbol] = snap
        return QuoteBatch(
            items=items,
            degraded=bool(data.get("degraded")),
            message=str(data.get("message") or ""),
            active_host=str(data.get("active_host") or ""),
        )


class LocalPytdxQuoteProvider:
    """In-process fallback when sidecar URL is unreachable (same host)."""

    def get_quotes(self, symbols: list[str]) -> QuoteBatch:
        from app.tdx_sidecar.quotes import fetch_quotes_batch

        data = fetch_quotes_batch(symbols)
        items = {}
        for row in data.get("items") or []:
            if isinstance(row, dict) and row.get("symbol"):
                items[str(row["symbol"])] = snap_from_dict(row)
        return QuoteBatch(
            items=items,
            degraded=bool(data.get("degraded")),
            message=str(data.get("message") or ""),
            active_host=str(data.get("active_host") or ""),
        )
