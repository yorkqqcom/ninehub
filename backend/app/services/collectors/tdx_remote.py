"""TDX remote collector — HTTP client wrapper for Sidecar batch APIs."""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from app.services.collectors.tdx_sidecar import TdxSidecarClient


class TdxRemoteCollector:
    """Fetch raw DataFrames from TDX Sidecar (vipdoc import / network bars)."""

    def __init__(
        self,
        base_url: str,
        api_token: str | None = None,
        *,
        install_root: str | None = None,
        paths: dict[str, Any] | None = None,
    ) -> None:
        self._client = TdxSidecarClient(base_url, api_token)
        self.install_root = install_root
        self.paths = paths or {}

    def fetch_vipdoc_bars(
        self,
        *,
        period: str = "1d",
        start_date: date | None = None,
        end_date: date | None = None,
        stock_codes: list[str] | None = None,
        incremental: bool = False,
        last_sync_date: date | None = None,
        limit_files: int | None = None,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        return self._client.vipdoc_import(
            period=period,
            start_date=start_date,
            end_date=end_date,
            stock_codes=stock_codes,
            incremental=incremental,
            last_sync_date=last_sync_date,
            limit_files=limit_files,
            install_root=self.install_root,
            paths=self.paths,
        )

    def fetch_network_bars(
        self,
        *,
        stock_codes: list[str],
        period: str,
        start_date: date,
        end_date: date,
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        return self._client.bars_batch(
            stock_codes=stock_codes,
            period=period,
            start_date=start_date,
            end_date=end_date,
            install_root=self.install_root,
            paths=self.paths,
        )
