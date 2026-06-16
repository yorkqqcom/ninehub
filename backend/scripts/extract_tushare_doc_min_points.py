"""CLI: extract min_points from Tushare document/2 page text (not sidebar link metadata).

Examples:
  python scripts/extract_tushare_doc_min_points.py --text "积分：需2000积分以上才可以调取本接口，5000积分以上频次会更高"
  python scripts/extract_tushare_doc_min_points.py --validate-corpus
  python scripts/extract_tushare_doc_min_points.py --doc-id 144 --doc-id 61 --write-cache
  python scripts/extract_tushare_doc_min_points.py --scope resolved --write-cache --sleep 0.35
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.scan.min_points_extractor import (  # noqa: E402
    extract_access_min_points,
    extract_from_doc_page,
    extract_points_section,
)
from app.services.tia.scan.tushare_doc_registry import (  # noqa: E402
    _API_CANONICAL_DOC_IDS,
    build_doc_page_url,
    load_doc_pages_cache,
    parse_api_name_from_doc_text,
    resolve_canonical_api_meta,
)
from app.services.tia.scan.tushare_doc_page_fetcher import (  # noqa: E402
    html_to_plain_text,
    parse_doc_page_content,
)

CORPUS_PATH = ROOT / "tests" / "fixtures" / "tushare_doc_min_points_corpus.json"
CACHE_PATH = ROOT / "app" / "catalog" / "providers" / "tushare_doc_pages_cache.json"


def load_corpus() -> list[dict]:
    if not CORPUS_PATH.is_file():
        return []
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return list(raw.get("cases", raw))


def run_corpus_validation() -> int:
    cases = load_corpus()
    if not cases:
        print(f"No corpus at {CORPUS_PATH}")
        return 1
    failed: list[str] = []
    for case in cases:
        text = case.get("text") or ""
        expected = case.get("min_points")
        got = extract_access_min_points(text)
        if got != expected:
            failed.append(
                f"  id={case.get('id')} expected={expected} got={got} "
                f"text={text[:80]!r}"
            )
    print(f"Corpus cases: {len(cases)} passed: {len(cases) - len(failed)} failed: {len(failed)}")
    if failed:
        print("\n-- failures --")
        for line in failed[:30]:
            print(line)
        if len(failed) > 30:
            print(f"  ... and {len(failed) - 30} more")
        return 1
    return 0


def resolve_target_doc_ids(scope: str, doc_ids: list[int] | None) -> list[int]:
    if doc_ids:
        return sorted(set(doc_ids))
    if scope == "canonical":
        return sorted(set(_API_CANONICAL_DOC_IDS.values()))
    from app.services.tia.scan.doc_points_resolver import resolve_doc_ids_for_scope

    return resolve_doc_ids_for_scope(scope)


def extract_from_live_pages(
    doc_ids: list[int],
    *,
    sleep_seconds: float,
    use_playwright: bool,
    login_if_needed: bool,
) -> dict[str, dict]:
    from app.services.tia.scan.tushare_doc_page_fetcher import fetch_doc_pages

    fetched = fetch_doc_pages(
        doc_ids,
        sleep_seconds=sleep_seconds,
        use_playwright=use_playwright,
        login_if_needed=login_if_needed,
    )
    out: dict[str, dict] = {}
    for doc_key, entry in fetched.items():
        raw_text = entry.get("raw_text") or ""
        if not raw_text and entry.get("error"):
            out[doc_key] = entry
            continue
        parsed = extract_from_doc_page(raw_text)
        row = dict(entry)
        if parsed.get("min_points") is not None:
            row["min_points"] = parsed["min_points"]
        if parsed.get("points_section"):
            row["points_section"] = parsed["points_section"]
        row["min_points_source"] = "doc_page_live"
        out[doc_key] = row
    return out


def apply_corpus_to_cache(corpus: list[dict], *, dry_run: bool) -> dict[str, int]:
    pages = load_doc_pages_cache()
    stats = {"updated": 0, "skipped": 0}
    for case in corpus:
        doc_id = case.get("doc_id")
        text = case.get("text")
        if doc_id is None or not text:
            stats["skipped"] += 1
            continue
        pts = extract_access_min_points(text)
        expected = case.get("min_points")
        if pts is None and expected is None:
            resolved_pts = None
        elif pts is not None:
            resolved_pts = pts
        elif expected is not None:
            resolved_pts = int(expected)
        else:
            stats["skipped"] += 1
            continue
        api = case.get("api") or parse_api_name_from_doc_text(text)
        row = {
            "api": api,
            "raw_text": normalize_plain_from_page_text(text),
            "source": "official_text",
            "min_points_source": "doc_page_parsed",
            "points_section": extract_points_section(text),
        }
        if resolved_pts is not None:
            row["min_points"] = resolved_pts
        pages[str(int(doc_id))] = row
        stats["updated"] += 1

    if not dry_run and stats["updated"]:
        payload = {
            "provider": "tushare",
            "source_url": "https://tushare.pro/document/2",
            "note": "Updated via extract_tushare_doc_min_points.py --apply-corpus",
            "page_count": len(pages),
            "pages": pages,
        }
        CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return stats


def normalize_plain_from_page_text(text: str) -> str:
    """Collapse page markdown / HTML-ish blobs into one-line plain text for cache."""
    lines = [ln.strip() for ln in text.replace("\r", "\n").split("\n") if ln.strip()]
    joined = " ".join(lines)
    return html_to_plain_text(joined) if "<" in joined else joined


def print_extract_report(rows: list[dict]) -> None:
    ok = sum(1 for r in rows if r.get("min_points") is not None)
    print(f"Extracted min_points: {ok}/{len(rows)}")
    for row in rows:
        doc_id = row.get("doc_id")
        api = row.get("api") or "?"
        pts = row.get("min_points")
        section = (row.get("points_section") or "")[:100]
        err = row.get("error")
        if err:
            print(f"  doc={doc_id} api={api} ERROR {err}")
        elif pts is None:
            print(f"  doc={doc_id} api={api} min_points=— section={section!r}")
        else:
            print(f"  doc={doc_id} api={api} min_points={pts} section={section!r}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract min_points from Tushare document/2 page body (not link metadata)"
    )
    parser.add_argument("--text", help="Extract from inline page plain text")
    parser.add_argument("--validate-corpus", action="store_true", help="Run fixture corpus (100+ cases)")
    parser.add_argument("--apply-corpus", action="store_true", help="Apply corpus texts to doc pages cache")
    parser.add_argument("--scope", choices=("resolved", "all", "canonical"), default="resolved")
    parser.add_argument("--doc-id", type=int, action="append", dest="doc_ids")
    parser.add_argument("--write-cache", action="store_true", help="Merge results into tushare_doc_pages_cache.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.35)
    parser.add_argument("--no-playwright", action="store_true")
    parser.add_argument("--no-login", action="store_true")
    parser.add_argument("--json", action="store_true", help="Print JSON report")
    args = parser.parse_args()

    if args.validate_corpus:
        sys.exit(run_corpus_validation())

    if args.text:
        parsed = extract_from_doc_page(args.text)
        if args.json:
            print(json.dumps(parsed, ensure_ascii=False, indent=2))
        else:
            print(f"min_points={parsed.get('min_points')}")
            if parsed.get("points_section"):
                print(f"section={parsed['points_section']}")
        return

    if args.apply_corpus:
        stats = apply_corpus_to_cache(load_corpus(), dry_run=args.dry_run)
        print(f"corpus apply updated={stats['updated']} skipped={stats['skipped']} dry_run={args.dry_run}")
        return

    doc_ids = resolve_target_doc_ids(args.scope, args.doc_ids)
    if not doc_ids:
        print("No doc_ids to process")
        sys.exit(1)

    fetched = extract_from_live_pages(
        doc_ids,
        sleep_seconds=args.sleep,
        use_playwright=not args.no_playwright,
        login_if_needed=not args.no_login,
    )

    rows: list[dict] = []
    for doc_key, entry in fetched.items():
        rows.append({"doc_id": int(doc_key), **entry})

    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        print_extract_report(rows)

    if args.write_cache and not args.dry_run:
        pages = load_doc_pages_cache()
        for doc_key, entry in fetched.items():
            if entry.get("error") and not entry.get("raw_text"):
                continue
            pages[doc_key] = entry
        payload = {
            "provider": "tushare",
            "source_url": "https://tushare.pro/document/2",
            "note": "Live extract via extract_tushare_doc_min_points.py",
            "page_count": len(pages),
            "pages": pages,
        }
        CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote cache {CACHE_PATH} pages={len(pages)}")


if __name__ == "__main__":
    main()
