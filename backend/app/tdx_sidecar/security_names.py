"""Shared stock display-name cache for Sidecar quotes/ranks.

pytdx ``get_security_quotes`` has no name field; names come from TDX export txt
(``stock_name``) loaded with the concept catalog.
"""

from __future__ import annotations

import threading

_lock = threading.RLock()
_names: dict[str, str] = {}


def set_stock_names(mapping: dict[str, str]) -> None:
    """Replace cache (called after successful catalog load)."""
    cleaned: dict[str, str] = {}
    for k, v in (mapping or {}).items():
        sym = str(k or "").strip().upper()
        name = str(v or "").strip()
        if sym and name:
            cleaned[sym] = name
    with _lock:
        _names.clear()
        _names.update(cleaned)


def lookup_stock_name(symbol: str) -> str:
    sym = str(symbol or "").strip().upper()
    if not sym:
        return ""
    with _lock:
        return str(_names.get(sym) or "")
