"""Persist parsed Tushare API doc specs (wctapi markdown cache)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_PROVIDERS = Path(__file__).resolve().parents[3] / "catalog" / "providers"
_SPECS_CACHE_PATH = _PROVIDERS / "tushare_api_specs_cache.json"

_specs_by_doc_cache: dict[str, dict[str, Any]] | None = None
_specs_by_name_cache: dict[str, dict[str, Any]] | None = None
_specs_cache_mtime: float = 0.0


def _invalidate_specs_index() -> None:
    global _specs_by_doc_cache, _specs_by_name_cache, _specs_cache_mtime
    _specs_by_doc_cache = None
    _specs_by_name_cache = None
    _specs_cache_mtime = 0.0


def _specs_file_mtime() -> float:
    try:
        return _SPECS_CACHE_PATH.stat().st_mtime if _SPECS_CACHE_PATH.is_file() else 0.0
    except OSError:
        return 0.0


def load_api_specs_cache() -> dict[str, dict[str, Any]]:
    global _specs_by_doc_cache, _specs_cache_mtime
    mtime = _specs_file_mtime()
    if _specs_by_doc_cache is not None and mtime == _specs_cache_mtime:
        return _specs_by_doc_cache
    if not _SPECS_CACHE_PATH.is_file():
        _specs_by_doc_cache = {}
        _specs_by_name_cache = None
        _specs_cache_mtime = mtime
        return _specs_by_doc_cache
    data = json.loads(_SPECS_CACHE_PATH.read_text(encoding="utf-8"))
    entries = data.get("entries") or data
    if isinstance(entries, dict):
        _specs_by_doc_cache = {str(k): v for k, v in entries.items() if isinstance(v, dict)}
    else:
        _specs_by_doc_cache = {}
    _specs_cache_mtime = mtime
    _specs_by_name_cache = None
    return _specs_by_doc_cache


def build_api_spec_by_name_index(
    *, cache: dict[str, dict[str, Any]] | None = None
) -> dict[str, dict[str, Any]]:
    """O(1) api_name → spec row; rebuilt when specs file mtime changes."""
    global _specs_by_name_cache, _specs_cache_mtime
    mtime = _specs_file_mtime()
    if cache is None and _specs_by_name_cache is not None and mtime == _specs_cache_mtime:
        return _specs_by_name_cache
    store = cache if cache is not None else load_api_specs_cache()
    index: dict[str, dict[str, Any]] = {}
    for doc_key, row in store.items():
        if not isinstance(row, dict):
            continue
        api = row.get("api")
        if not api:
            continue
        merged = {**row, "doc_id": row.get("doc_id", int(doc_key))}
        index[str(api).lower()] = merged
    if cache is None:
        _specs_by_name_cache = index
        _specs_cache_mtime = mtime
    return index


def specs_cache_path() -> Path:
    return _SPECS_CACHE_PATH


def save_api_specs_cache(entries: dict[str, dict[str, Any]]) -> None:
    _invalidate_specs_index()
    payload = {
        "provider": "tushare",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }
    _SPECS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SPECS_CACHE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_api_spec(doc_id: int | str, *, cache: dict[str, dict] | None = None) -> dict[str, Any] | None:
    store = cache if cache is not None else load_api_specs_cache()
    row = store.get(str(int(doc_id)))
    return row if isinstance(row, dict) else None


def get_api_spec_by_name(api_name: str, *, cache: dict[str, dict] | None = None) -> dict[str, Any] | None:
    if cache is not None:
        api = api_name.strip().lower()
        for row in cache.values():
            if isinstance(row, dict) and str(row.get("api", "")).lower() == api:
                return row
        return None
    return build_api_spec_by_name_index().get(api_name.strip().lower())


def merge_api_spec_entry(doc_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    _invalidate_specs_index()
    cache = load_api_specs_cache()
    key = str(int(doc_id))
    prev = cache.get(key) or {}
    merged = {**prev, **patch, "doc_id": int(doc_id)}
    cache[key] = merged
    save_api_specs_cache(cache)
    return merged


def build_api_to_doc_id_map(*, cache: dict[str, dict[str, Any]] | None = None) -> dict[str, int]:
    """api_name → doc_id from wctapi specs cache (authoritative when present)."""
    store = cache if cache is not None else load_api_specs_cache()
    out: dict[str, int] = {}
    for doc_key, row in store.items():
        if not isinstance(row, dict):
            continue
        api = row.get("api")
        if not api:
            continue
        out[str(api).lower()] = int(doc_key)
    return out


def spec_to_page_cache_entry(spec: dict[str, Any]) -> dict[str, Any]:
    """Build doc_pages_cache row from parsed wctapi spec."""
    api = spec.get("api")
    desc = str(spec.get("description") or "").strip()
    pts = spec.get("min_points")
    parts: list[str] = []
    if api:
        parts.append(f"接口：{api}")
    if desc:
        parts.append(f"描述：{desc}")
    if pts is not None:
        parts.append(f"积分：{int(pts)}积分")
    entry: dict[str, Any] = {
        "api": api,
        "raw_text": " ".join(parts),
        "min_points_source": "wctapi_md",
        "fetcher": "wctapi_md",
        "fetched_url": spec.get("doc_url"),
    }
    if pts is not None:
        entry["min_points"] = int(pts)
    return entry
