"""Sync Tushare doc_id=14 catalog into bundled JSON for TIA scan.

Authoritative index: https://tushare.pro/document/2?doc_id=14
Per-interface min_points: each API doc page (NOT doc_id=108, stale).

Run: python scripts/sync_tushare_doc14_catalog.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDERS = ROOT / "app" / "catalog" / "providers"
OUT = PROVIDERS / "tushare_doc14_catalog.json"

DEPRECATED_DOC_IDS = frozenset({108})

# doc14 section names (doc_id=14 左侧目录)
CATEGORY_TO_DOC14: dict[str, str] = {
    "基础": "股票数据",
    "行情": "行情数据",
    "财务": "财务数据",
    "参考": "参考数据",
    "资金": "资金流向数据",
    "两融": "两融及转融通",
    "特色": "特色数据",
    "港股通": "沪深港通",
    "概念": "参考数据",
    "热榜": "特色数据",
    "研报": "特色数据",
    "调研": "股票数据",
    "指数": "指数专题",
    "基金": "公募基金",
    "期货": "期货数据",
    "期权": "期权数据",
    "债券": "债券专题",
    "宏观": "宏观经济",
}

# Manual additions / overrides aligned with doc14 listing (api from each doc page)
DOC14_MANUAL: list[dict] = [
    {"doc_id": 356, "label": "涨跌停列表", "category": "打板专题", "api": "limit_list", "min_points": 2000, "probe_category": "trade_date"},
]


def _load_json(name: str) -> dict:
    return json.loads((PROVIDERS / name).read_text(encoding="utf-8"))


def _api_to_entry(item: dict) -> dict | None:
    doc_id = item.get("doc_id")
    api = item.get("api")
    if doc_id is None or not api or int(doc_id) in DEPRECATED_DOC_IDS:
        return None
    cat = CATEGORY_TO_DOC14.get(item.get("category") or "", "其他")
    return {
        "doc_id": int(doc_id),
        "label": item.get("label") or api,
        "category": cat,
        "api": api,
        "min_points": item.get("min_points"),
        "probe_category": item.get("probe_category") or "none",
    }


def build_entries() -> list[dict]:
    by_doc_id: dict[int, dict] = {}
    for path in ("tushare_stock_official_apis.json", "tushare_official_apis.json"):
        raw = _load_json(path)
        for item in raw.get("apis", []):
            entry = _api_to_entry(item)
            if entry:
                by_doc_id[entry["doc_id"]] = entry
    for item in DOC14_MANUAL:
        if int(item["doc_id"]) not in DEPRECATED_DOC_IDS:
            by_doc_id[int(item["doc_id"])] = item
    return sorted(by_doc_id.values(), key=lambda x: x["doc_id"])


def main() -> None:
    entries = build_entries()
    payload = {
        "provider": "tushare",
        "source_doc_id": 14,
        "source_url": "https://tushare.pro/document/2?doc_id=14",
        "deprecated_doc_ids": sorted(DEPRECATED_DOC_IDS),
        "version": "2025-06-doc14",
        "note": "索引来自 doc_id=14 接口清单；积分以各接口 doc 页为准；doc_id=108 已弃用",
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(entries)} entries to {OUT}")


if __name__ == "__main__":
    main()
