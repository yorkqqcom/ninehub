"""One-shot: materialize sidebar fixtures from bundled MCP markdown snapshot."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "scripts" / "fixtures"
SNAPSHOT = Path(__file__).with_name("mcp_document2_sidebar.snapshot.md")

sys.path.insert(0, str(ROOT))
from app.services.tia.scan.tushare_sidebar_parser import parse_sidebar_markdown  # noqa: E402


def main() -> None:
    if not SNAPSHOT.is_file():
        print(f"Missing {SNAPSHOT}", file=sys.stderr)
        sys.exit(1)
    text = SNAPSHOT.read_text(encoding="utf-8")
    links = parse_sidebar_markdown(text)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    md_out = FIXTURES / "tushare_document2_sidebar.md"
    md_out.write_text(text, encoding="utf-8")
    json_out = FIXTURES / "tushare_document2_sidebar_links.json"
    json_out.write_text(
        json.dumps({"links": links}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(links)} links -> {md_out.name}, {json_out.name}")


if __name__ == "__main__":
    main()
