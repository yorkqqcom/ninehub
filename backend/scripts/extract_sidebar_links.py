"""Extract doc_id links from MCP markdown and merge into sidebar fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.scan.tushare_sidebar_parser import parse_sidebar_markdown  # noqa: E402

SNAPSHOT = ROOT / "scripts" / "mcp_document2_sidebar.snapshot.md"
OUT_MD = ROOT / "scripts" / "fixtures" / "tushare_document2_sidebar.md"
OUT_JSON = ROOT / "scripts" / "fixtures" / "tushare_document2_sidebar_links.json"


def main() -> None:
    if not SNAPSHOT.is_file():
        print(f"Missing {SNAPSHOT}", file=sys.stderr)
        sys.exit(1)
    text = SNAPSHOT.read_text(encoding="utf-8")
    links = parse_sidebar_markdown(text)
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(text, encoding="utf-8")
    OUT_JSON.write_text(json.dumps({"links": links}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Extracted {len(links)} sidebar links -> {OUT_MD.name}")


if __name__ == "__main__":
    main()
