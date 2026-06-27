"""TDX provider scan adapter (bundled catalog index)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.tia.scan.index_loader import load_bundled_index, load_official_index
from app.services.tia.scan.types import OfficialIndexSnapshot, ScanOptions


class TdxScanAdapter:
    provider = "tdx"

    def load_official_index(self, options: ScanOptions) -> OfficialIndexSnapshot:
        snapshot = load_official_index(self.provider, options)
        if snapshot.total == 0:
            bundled = load_bundled_index(self.provider)
            if bundled.total > 0:
                return bundled
            return OfficialIndexSnapshot(
                provider=self.provider,
                apis=[],
                source="not_implemented",
                version="0",
                total=0,
            )
        return snapshot

    def resolve_credentials(self, session: Session) -> dict:
        from app.services.tia.credentials_tdx import resolve_tdx_collect_credentials

        try:
            return resolve_tdx_collect_credentials(session, None)
        except Exception:
            return {
                "token": None,
                "account_points": 0,
                "max_calls_per_minute": None,
                "source_id": None,
                "source_name": None,
                "from_data_source": False,
                "provider": "tdx",
                "note": "TDX Sidecar credentials not configured",
            }
