"""Generate bundled default TIA proposals from document/2 sidebar index."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.tia.default_proposal_seed import write_default_proposals_file  # noqa: E402


def main() -> None:
    out = write_default_proposals_file(index_scope="stock_a")
    import json

    payload = json.loads(out.read_text(encoding="utf-8"))
    print(f"Wrote {len(payload.get('items', []))} default proposals -> {out}")


if __name__ == "__main__":
    main()
