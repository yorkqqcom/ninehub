"""Load official API index: document/2 sidebar with optional live HTTP refresh."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.services.tia.scan.types import OfficialApiEntry, OfficialIndexSnapshot, ScanOptions

_PROVIDERS_DIR = Path(__file__).resolve().parents[3] / "catalog" / "providers"

LIVE_INDEX_URLS: dict[str, str] = {
    "tushare": "https://tushare.pro/document/2",
    "akshare": "https://akshare.akfamily.xyz/data/index.html",
}


def bundled_index_path(provider: str, index_scope: str = "mixed") -> Path:
    if provider == "tushare" and index_scope == "stock_a":
        return _PROVIDERS_DIR / "tushare_stock_official_apis.json"
    return _PROVIDERS_DIR / f"{provider}_official_apis.json"


def load_bundled_index(provider: str, index_scope: str = "mixed") -> OfficialIndexSnapshot:
    path = bundled_index_path(provider, index_scope)
    if not path.is_file():
        return OfficialIndexSnapshot(provider=provider, apis=[], source="bundled_missing")
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = [OfficialApiEntry.from_dict(item) for item in raw.get("apis", [])]
    return OfficialIndexSnapshot(
        provider=provider,
        apis=entries,
        source="bundled",
        version=raw.get("version"),
        total=len(entries),
        scope=raw.get("scope") or index_scope,
    )


def fetch_live_index(provider: str) -> OfficialIndexSnapshot | None:
    """Try live fetch; SPA shell only today — returns None (caller uses bundled sidebar)."""
    url = LIVE_INDEX_URLS.get(provider)
    if not url:
        return None
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
        _ = response.text
        return None
    except Exception:
        return None


def load_document2_index(provider: str, index_scope: str) -> OfficialIndexSnapshot:
    if provider != "tushare":
        return OfficialIndexSnapshot(provider=provider, apis=[], source="document2_unsupported")
    from app.services.tia.scan.tushare_doc_catalog import load_document2_sidebar_index

    return load_document2_sidebar_index(index_scope=index_scope)


def load_doc14_index(provider: str, index_scope: str) -> OfficialIndexSnapshot:
    if provider != "tushare":
        return OfficialIndexSnapshot(provider=provider, apis=[], source="doc14_unsupported")
    from app.services.tia.scan.tushare_doc_catalog import load_doc14_official_index

    return load_doc14_official_index(index_scope=index_scope)


def load_official_index(provider: str, options: ScanOptions) -> OfficialIndexSnapshot:
    """Resolve official index by mode and source preference."""
    scope = options.index_scope
    source = options.index_source

    if source == "document2":
        snap = load_document2_index(provider, scope)
        if snap.apis:
            return snap
        bundled = load_bundled_index(provider, scope)
        bundled.source = "bundled_fallback"
        return bundled

    if source == "doc14":
        snap = load_doc14_index(provider, scope)
        if snap.apis:
            return snap
        bundled = load_bundled_index(provider, scope)
        bundled.source = "bundled_fallback"
        return bundled

    if source == "bundled":
        return load_bundled_index(provider, scope)

    if source == "live":
        live = fetch_live_index(provider)
        if live is not None:
            return live
        snap = load_document2_index(provider, scope)
        if snap.apis:
            snap.source = "document2_fallback"
            return snap
        bundled = load_bundled_index(provider, scope)
        bundled.source = "bundled_fallback"
        return bundled

    # auto: full scan uses document/2 sidebar snapshot only (no doc14 drift)
    if options.mode == "full":
        sidebar = load_document2_index(provider, scope)
        if sidebar.apis:
            return sidebar
        return load_bundled_index(provider, scope)

    sidebar = load_document2_index(provider, scope)
    if sidebar.apis:
        return sidebar
    doc14 = load_doc14_index(provider, scope)
    if doc14.apis:
        doc14.source = "doc14_fallback"
        return doc14
    return load_bundled_index(provider, scope)


def save_bundled_index(provider: str, payload: dict[str, Any]) -> None:
    """Test/helper: write bundled snapshot."""
    path = bundled_index_path(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
