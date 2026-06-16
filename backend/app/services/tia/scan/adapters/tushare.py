"""Tushare provider scan adapter."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.tia.credentials import resolve_tushare_scan_credentials
from app.services.tia.scan.index_loader import load_official_index
from app.services.tia.scan.types import OfficialIndexSnapshot, ScanOptions


class TushareScanAdapter:
    provider = "tushare"

    def load_official_index(self, options: ScanOptions) -> OfficialIndexSnapshot:
        return load_official_index(self.provider, options)

    def resolve_credentials(self, session: Session) -> dict:
        return resolve_tushare_scan_credentials(session)
