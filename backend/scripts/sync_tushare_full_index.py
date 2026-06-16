"""Merge sidebar MCP snapshot + doc registry into full document/2 index."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.scan.tushare_doc_registry import (  # noqa: E402
    build_api_by_doc_id,
    load_doc_pages_cache,
    resolve_sidebar_entry,
)
from app.services.tia.scan.tushare_sidebar_parser import parse_sidebar_markdown  # noqa: E402

PROVIDERS = ROOT / "app" / "catalog" / "providers"
FIXTURES = ROOT / "scripts" / "fixtures"
SNAPSHOT = ROOT / "scripts" / "mcp_document2_sidebar.snapshot.md"
OUT = PROVIDERS / "tushare_document2_sidebar.json"
DEPRECATED = frozenset({108})


def load_sidebar_links(md_path: Path | None) -> list[dict]:
    if md_path and md_path.is_file():
        return parse_sidebar_markdown(md_path.read_text(encoding="utf-8"))
    links_json = FIXTURES / "tushare_document2_sidebar_links.json"
    if links_json.is_file():
        return json.loads(links_json.read_text(encoding="utf-8")).get("links", [])
    return []


def supplement_links_from_registry(links: list[dict], api_by_doc: dict[int, dict]) -> list[dict]:
    """Keep sidebar snapshot only — registry supplements use stale doc14 ids (404 on site)."""
    _ = api_by_doc
    return list(links)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync full document/2 sidebar + doc_id registry")
    parser.add_argument("--md", help="Sidebar markdown path")
    args = parser.parse_args()

    md_path = Path(args.md) if args.md else None
    if md_path is None:
        for candidate in (SNAPSHOT, FIXTURES / "tushare_document2_sidebar.md", PROVIDERS / "tushare_document2_sidebar.md"):
            if candidate.is_file():
                md_path = candidate
                break

    links = load_sidebar_links(md_path)
    if not links:
        print("No sidebar links found", file=sys.stderr)
        sys.exit(1)

    api_by_doc = build_api_by_doc_id()
    links = supplement_links_from_registry(links, api_by_doc)
    page_cache = load_doc_pages_cache()

    entries: list[dict] = []
    resolved = 0
    for link in links:
        if int(link["doc_id"]) in DEPRECATED:
            continue
        enriched = resolve_sidebar_entry(link, api_by_doc=api_by_doc, page_cache=page_cache)
        if enriched.get("skipped"):
            continue
        entries.append(enriched)
        if enriched.get("resolved"):
            resolved += 1

    entries.sort(key=lambda x: x["doc_id"])
    payload = {
        "provider": "tushare",
        "source_url": "https://tushare.pro/document/2",
        "deprecated_doc_ids": sorted(DEPRECATED),
        "version": "2025-06-document2-full",
        "note": "document/2 左侧菜单 + doc_id 注册表补全；遍历 doc_id 扫描",
        "sidebar_link_count": len(links),
        "resolved_api_count": resolved,
        "unresolved_doc_count": len(entries) - resolved,
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Sidebar {len(links)} links, entries {len(entries)}, resolved api {resolved} -> {OUT}")


if __name__ == "__main__":
    main()
