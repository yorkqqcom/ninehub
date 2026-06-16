"""Tushare API quota metadata (runtime via bundled doc registry + tia_overrides)."""

from typing import Any, Dict

# Built-in catalog removed: local APIs come from tia_overrides only.
TUSHARE_API_QUOTA: Dict[str, Dict[str, Any]] = {}
