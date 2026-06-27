"""HTTP client for TDX Sidecar batch APIs."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pandas as pd

from app.core.exceptions import ValidationError


class TdxSidecarClient:
    def __init__(
        self,
        base_url: str,
        api_token: str | None = None,
        *,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token or ""
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self.api_token:
            return {}
        return {"Authorization": f"Bearer {self.api_token}"}

    def health(self) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{self.base_url}/api/v1/market/health",
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def vipdoc_status(self, *, install_root: str | None = None, paths: dict | None = None) -> dict[str, Any]:
        params: dict[str, str] = {}
        if install_root:
            params["install_root"] = install_root
        if paths and paths.get("vipdoc_root"):
            params["vipdoc_root"] = str(paths["vipdoc_root"])
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{self.base_url}/api/v1/market/vipdoc/status",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def sync_tdx_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.put(
                f"{self.base_url}/api/v1/market/tdx-config",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

    def vipdoc_import(
        self,
        *,
        period: str = "1d",
        start_date: date | None = None,
        end_date: date | None = None,
        stock_codes: list[str] | None = None,
        incremental: bool = False,
        last_sync_date: date | None = None,
        limit_files: int | None = None,
        install_root: str | None = None,
        paths: dict[str, Any] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        body: dict[str, Any] = {
            "period": period,
            "incremental": incremental,
        }
        if start_date:
            body["start_date"] = start_date.isoformat()
        if end_date:
            body["end_date"] = end_date.isoformat()
        if last_sync_date:
            body["last_sync_date"] = last_sync_date.isoformat()
        if stock_codes:
            body["stock_codes"] = stock_codes
        if limit_files:
            body["limit_files"] = limit_files
        if install_root:
            body["install_root"] = install_root
        if paths:
            body["paths"] = paths
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/api/v1/market/vipdoc/import",
                json=body,
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                raise ValidationError(f"Sidecar vipdoc/import failed: {resp.text}")
            data = resp.json()
        items = data.get("items") or []
        meta = data.get("meta") or {}
        if not items:
            return pd.DataFrame(), meta
        df = pd.DataFrame(items)
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        return df, meta

    def bars_batch(
        self,
        *,
        stock_codes: list[str],
        period: str,
        start_date: date,
        end_date: date,
        install_root: str | None = None,
        paths: dict[str, Any] | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        body: dict[str, Any] = {
            "period": period,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "stock_codes": stock_codes,
        }
        if install_root:
            body["install_root"] = install_root
        if paths:
            body["paths"] = paths
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/api/v1/market/bars/batch",
                json=body,
                headers=self._headers(),
            )
            if resp.status_code >= 400:
                raise ValidationError(f"Sidecar bars/batch failed: {resp.text}")
            data = resp.json()
        items = data.get("items") or []
        meta = data.get("meta") or {}
        if not items:
            return pd.DataFrame(), meta
        df = pd.DataFrame(items)
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        return df, meta

    def concept_catalog(
        self,
        trade_date: date,
        *,
        install_root: str | None = None,
        paths: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {"trade_date": trade_date.isoformat()}
        if install_root:
            params["install_root"] = install_root
        if paths and paths.get("hq_cache_root"):
            params["hq_cache_root"] = str(paths["hq_cache_root"])
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(
                f"{self.base_url}/api/v1/market/concept-catalog",
                params=params,
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()
