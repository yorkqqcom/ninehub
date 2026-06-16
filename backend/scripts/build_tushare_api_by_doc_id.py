"""Build tushare_api_by_doc_id.json from all catalog/bundled sources."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.scan.tushare_doc_registry import build_api_by_doc_id  # noqa: E402

OUT = ROOT / "app" / "catalog" / "providers" / "tushare_api_by_doc_id.json"


def main() -> None:
    by_doc = build_api_by_doc_id()
    entries = sorted(by_doc.values(), key=lambda x: x["doc_id"])
    resolved = sum(1 for e in entries if e.get("api"))
    payload = {
        "provider": "tushare",
        "version": "2025-06-doc-registry",
        "total": len(entries),
        "resolved_api_count": resolved,
        "entries": entries,
        "by_doc_id": {str(e["doc_id"]): e for e in entries},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(entries)} doc_ids ({resolved} with api) -> {OUT}")


if __name__ == "__main__":
    main()
