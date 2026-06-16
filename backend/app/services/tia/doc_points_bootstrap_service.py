"""Bulk bootstrap min_points from document/2 page snapshots (100-iteration landing).

Design:
  Iteration 1-10   — pattern audit on live page corpus
  Iteration 11-30  — expand regex for 积分段落 (起/后可用/VIP/频次隔离)
  Iteration 31-60  — fetch all canonical doc_ids, store plain_text snapshot
  Iteration 61-80  — extract + merge cache, reject sidebar_seed fabricated hints
  Iteration 81-100 — coverage audit, proposal enrichment verification
  Iteration 500    — API-live min_points via TIA scan probe (pro_response parser)
  Iteration 20     — Phase A/B/C: audit tiers, page-first merge, seed governance

Phase C governance (no runtime logic change):
  1. ``POST /api/v1/tia/doc-pages/sync`` — refresh ``doc_pages_cache`` from live pages
  2. bootstrap ``patch_sidebar_from_pages`` — rewrite sidebar.api from page body
  3. ``scripts/validate_plain_doc_seeds.py`` — CI gate for ``_live_doc_plain_seeds.py``
  4. bundled JSON (doc14 / stock_official) — audit-only; never authoritative for api name

Single source of truth: document/2 page body text only.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.tia.scan.min_points_extractor import (
    extract_access_min_points,
    extract_from_doc_page,
    extract_points_section,
    normalize_doc_plain_text,
)
from app.services.tia.scan.tushare_doc_registry import (
    load_doc_pages_cache,
    parse_api_name_from_doc_text,
    resolve_canonical_api_meta,
)

_PROVIDERS = Path(__file__).resolve().parents[2] / "catalog" / "providers"
_CACHE_PATH = _PROVIDERS / "tushare_doc_pages_cache.json"
_SIDEBAR_PATH = _PROVIDERS / "tushare_document2_sidebar.json"


def list_canonical_doc_targets() -> list[dict[str, Any]]:
    """All resolved sidebar APIs mapped to canonical doc_id."""
    if not _SIDEBAR_PATH.is_file():
        return []
    raw = json.loads(_SIDEBAR_PATH.read_text(encoding="utf-8"))
    resolved = [e for e in raw.get("entries", []) if e.get("resolved") and e.get("api")]
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for entry in sorted(resolved, key=lambda e: str(e.get("api", ""))):
        api = str(entry["api"])
        if api in seen:
            continue
        seen.add(api)
        canonical = resolve_canonical_api_meta(api) or {}
        doc_id = int(canonical.get("doc_id") or entry["doc_id"])
        out.append(
            {
                "api": api,
                "doc_id": doc_id,
                "label": entry.get("label") or canonical.get("label"),
            }
        )
    return sorted(out, key=lambda r: r["doc_id"])


def markdown_or_plain_to_page_text(content: str) -> str:
    """Convert MCP markdown fetch or plain text to a single-line page body for parsing."""
    if not content:
        return ""
    lines: list[str] = []
    for raw_line in content.replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = line.strip("* ").strip()
        if line:
            lines.append(line)
    joined = " ".join(lines)
    return normalize_doc_plain_text(joined)


def parse_snapshot_page(doc_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    """Build cache row from one snapshot page entry."""
    raw = payload.get("plain_text") or payload.get("markdown") or payload.get("text") or ""
    plain = markdown_or_plain_to_page_text(str(raw))
    api = payload.get("api") or parse_api_name_from_doc_text(plain)
    parsed = extract_from_doc_page(plain)
    row: dict[str, Any] = {
        "api": api,
        "raw_text": plain,
        "source": "official_text",
        "min_points_source": "doc_page_parsed",
        "fetched_url": payload.get("url") or f"https://tushare.pro/document/2?doc_id={doc_id}",
    }
    if parsed.get("points_section"):
        row["points_section"] = parsed["points_section"]
    if parsed.get("min_points") is not None:
        row["min_points"] = int(parsed["min_points"])
    if payload.get("fetcher"):
        row["fetcher"] = payload["fetcher"]
    return row


def bootstrap_doc_points_from_snapshot(
    snapshot_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    pages_in = snapshot.get("pages", snapshot)
    cache = load_doc_pages_cache()
    merged = 0
    with_points = 0
    no_points = 0
    gaps: list[dict[str, Any]] = []

    for doc_key, payload in pages_in.items():
        doc_id = int(doc_key)
        row = parse_snapshot_page(doc_id, payload if isinstance(payload, dict) else {"text": payload})
        if not row.get("api"):
            continue
        cache[str(doc_id)] = row
        merged += 1
        if row.get("min_points") is not None:
            with_points += 1
        else:
            no_points += 1
            if len(gaps) < 30:
                gaps.append({"doc_id": doc_id, "api": row.get("api"), "section": row.get("points_section")})

    if not dry_run and merged:
        payload = {
            "provider": "tushare",
            "source_url": "https://tushare.pro/document/2",
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "note": f"Bootstrap from {snapshot_path.name}",
            "page_count": len(cache),
            "pages": cache,
        }
        _CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        from app.services.tia.doc_pages_sync_service import DocPagesSyncService

        DocPagesSyncService().patch_sidebar_from_pages(cache)

    return {
        "merged": merged,
        "with_points": with_points,
        "no_points": no_points,
        "sample_gaps": gaps,
        "cache_path": str(_CACHE_PATH),
    }


def run_bootstrap_audit() -> dict[str, Any]:
    targets = list_canonical_doc_targets()
    cache = load_doc_pages_cache()
    missing_rows: list[dict[str, Any]] = []
    with_points = 0
    for target in targets:
        doc_id = target["doc_id"]
        api = target["api"]
        entry = cache.get(str(doc_id), {})
        pts = entry.get("min_points")
        if pts is None and entry.get("raw_text"):
            pts = extract_access_min_points(entry["raw_text"])
        if pts is not None:
            with_points += 1
        else:
            missing_rows.append(
                {
                    "doc_id": doc_id,
                    "api": api,
                    "has_raw_text": bool(entry.get("raw_text")),
                    "section": entry.get("points_section"),
                }
            )
    return {
        "targets": len(targets),
        "with_points": with_points,
        "missing": len(missing_rows),
        "missing_rows": missing_rows,
    }


def ensure_doc_pages_cache_from_seeds(*, backend_root: Path | None = None) -> dict[str, Any] | None:
    """Bootstrap ``tushare_doc_pages_cache.json`` from bundled plain seeds when missing."""
    if _CACHE_PATH.is_file() and len(load_doc_pages_cache()) >= 40:
        return None

    root = backend_root or Path(__file__).resolve().parents[3]
    snapshot = root / "tests" / "fixtures" / "tushare_doc_pages_live_snapshot.json"
    if not snapshot.is_file():
        import subprocess
        import sys

        subprocess.run(
            [sys.executable, str(root / "scripts" / "compile_live_doc_snapshot.py")],
            cwd=root,
            check=True,
        )
    result = bootstrap_doc_points_from_snapshot(snapshot)
    from app.services.tia.doc_pages_sync_service import DocPagesSyncService

    DocPagesSyncService().patch_sidebar_from_pages(load_doc_pages_cache())
    return result
