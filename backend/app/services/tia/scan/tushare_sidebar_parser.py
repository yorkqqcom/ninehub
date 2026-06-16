"""Parse Tushare document/2 left sidebar links from fetched markdown."""

from __future__ import annotations

import re

DOC_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((?:https://tushare\.pro)?/document/2\?doc_id=(\d+)\)"
)
CATEGORY_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
SUBCATEGORY_HEADING_RE = re.compile(r"^###\s+(.+?)\s*$")

# Non-API doc pages in sidebar (platform docs, stale tables)
SKIP_DOC_IDS = frozenset({108})


def parse_sidebar_markdown(text: str) -> list[dict]:
    """Extract doc_id + label + category from document/2 sidebar markdown."""
    entries: list[dict] = []
    seen_doc_ids: set[int] = set()
    category: str | None = None
    subcategory: str | None = None

    for line in text.splitlines():
        stripped = line.strip()
        cat_m = CATEGORY_HEADING_RE.match(stripped)
        if cat_m:
            category = cat_m.group(1).strip()
            subcategory = None
            continue
        sub_m = SUBCATEGORY_HEADING_RE.match(stripped)
        if sub_m:
            subcategory = sub_m.group(1).strip()
            continue

        for label, doc_id_str in DOC_LINK_RE.findall(stripped):
            doc_id = int(doc_id_str)
            if doc_id in SKIP_DOC_IDS or doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)
            entries.append(
                {
                    "doc_id": doc_id,
                    "label": label.strip(),
                    "category": category,
                    "subcategory": subcategory,
                }
            )

    return entries
