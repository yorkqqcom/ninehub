"""AkShare provider scan adapter (index snapshot stub for future live crawl)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.tia.scan.index_loader import load_bundled_index, load_official_index
from app.services.tia.scan.types import OfficialIndexSnapshot, ScanOptions


class AkShareScanAdapter:
    provider = "akshare"

    def load_official_index(self, options: ScanOptions) -> OfficialIndexSnapshot:
        if options.mode == "catalog":
            return OfficialIndexSnapshot(
                provider=self.provider,
                apis=[],
                source="catalog_stub",
                version="0",
                total=0,
            )
        snapshot = load_official_index(self.provider, options)
        if snapshot.total == 0:
            bundled = load_bundled_index(self.provider)
            if bundled.total == 0:
                return OfficialIndexSnapshot(
                    provider=self.provider,
                    apis=[],
                    source="not_implemented",
                    version="0",
                    total=0,
                )
        return snapshot

    def resolve_credentials(self, session: Session) -> dict:
        return {
            "token": None,
            "account_points": 0,
            "max_calls_per_minute": None,
            "source_id": None,
            "source_name": None,
            "from_data_source": False,
            "note": "AkShare probes not implemented; index-only scan",
        }
