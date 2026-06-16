"""Fetch document/2 pages into live snapshot JSON for min_points bootstrap.

Uses Playwright when available; falls back to httpx (SPA shell only).

  python scripts/fetch_tushare_doc_pages_snapshot.py --output tests/fixtures/tushare_doc_pages_live_snapshot.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.doc_points_bootstrap_service import list_canonical_doc_targets  # noqa: E402
from app.services.tia.scan.min_points_extractor import extract_access_min_points  # noqa: E402


def fetch_pages_playwright(doc_ids: list[int], *, sleep: float) -> dict[str, dict]:
    from playwright.sync_api import sync_playwright

    pages: dict[str, dict] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        for idx, doc_id in enumerate(doc_ids):
            url = f"https://tushare.pro/document/2?doc_id={doc_id}"
            try:
                page.goto(url, wait_until="networkidle", timeout=45000)
                try:
                    page.wait_for_selector("text=接口", timeout=20000)
                except Exception:
                    pass
                page.wait_for_timeout(1200)
                plain = page.inner_text("body")
                pages[str(doc_id)] = {
                    "url": url,
                    "plain_text": plain,
                    "fetcher": "playwright_snapshot",
                }
            except Exception as exc:
                pages[str(doc_id)] = {"url": url, "error": str(exc)}
            if idx > 0 and sleep > 0:
                time.sleep(sleep)
        browser.close()
    return pages


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch Tushare doc pages into snapshot JSON")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "tests" / "fixtures" / "tushare_doc_pages_live_snapshot.json",
    )
    parser.add_argument("--doc-id", type=int, action="append", dest="doc_ids")
    parser.add_argument("--sleep", type=float, default=0.3)
    args = parser.parse_args()

    if args.doc_ids:
        doc_ids = sorted(set(args.doc_ids))
    else:
        doc_ids = sorted({t["doc_id"] for t in list_canonical_doc_targets()})

    pages = fetch_pages_playwright(doc_ids, sleep=args.sleep)
    with_pts = 0
    for doc_key, row in pages.items():
        plain = row.get("plain_text") or ""
        pts = extract_access_min_points(plain)
        if pts is not None:
            row["min_points_preview"] = pts
            with_pts += 1

    payload = {
        "provider": "tushare",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "doc_count": len(pages),
        "with_points_preview": with_pts,
        "pages": pages,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output} pages={len(pages)} with_points_preview={with_pts}")


if __name__ == "__main__":
    main()
