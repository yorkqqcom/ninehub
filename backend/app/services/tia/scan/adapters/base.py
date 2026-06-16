"""Provider scan adapter protocol for TIA full scan."""

from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session

from app.services.tia.scan.types import OfficialIndexSnapshot, ScanOptions


class ProviderScanAdapter(Protocol):
    """Each data vendor implements index loading + credential resolution."""

    provider: str

    def load_official_index(self, options: ScanOptions) -> OfficialIndexSnapshot:
        """Load vendor official API catalog (bundled snapshot or live fetch)."""

    def resolve_credentials(self, session: Session) -> dict:
        """Return token/quota fields needed for live API probes."""
