"""Provider scan adapter registry."""

from __future__ import annotations

from app.core.exceptions import ValidationError
from app.services.tia.scan.adapters.akshare import AkShareScanAdapter
from app.services.tia.scan.adapters.base import ProviderScanAdapter
from app.services.tia.scan.adapters.tushare import TushareScanAdapter

_REGISTRY: dict[str, ProviderScanAdapter] = {
    "tushare": TushareScanAdapter(),
    "akshare": AkShareScanAdapter(),
}


def get_scan_adapter(provider: str) -> ProviderScanAdapter:
    adapter = _REGISTRY.get(provider)
    if adapter is None:
        raise ValidationError(f"Unsupported scan provider: {provider}")
    return adapter


def list_scan_providers() -> list[str]:
    return sorted(_REGISTRY.keys())
