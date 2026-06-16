"""Compile live doc plain seeds into snapshot JSON for bootstrap."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts._live_doc_plain_seeds import PLAIN_SEEDS  # noqa: E402
from app.services.tia.scan.min_points_extractor import extract_access_min_points  # noqa: E402

OUT = ROOT / "tests" / "fixtures" / "tushare_doc_pages_live_snapshot.json"


def main() -> None:
    pages: dict[str, dict] = {}
    with_pts = 0
    for doc_id, plain in sorted(PLAIN_SEEDS.items()):
        pts = extract_access_min_points(plain)
        row = {
            "plain_text": plain,
            "url": f"https://tushare.pro/document/2?doc_id={doc_id}",
            "fetcher": "mcp_live_compile",
        }
        if pts is not None:
            row["min_points_preview"] = pts
            with_pts += 1
        pages[str(doc_id)] = row

    payload = {
        "provider": "tushare",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "doc_count": len(pages),
        "with_points_preview": with_pts,
        "pages": pages,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {OUT} pages={len(pages)} with_points={with_pts}")


if __name__ == "__main__":
    main()
