"""Tushare doc_id registry: resolve api/min_points/probe from all bundled sources."""

from __future__ import annotations

import json
import re
from pathlib import Path

_DEPRECATED_DOC_IDS = frozenset({35, 108})  # 35: hs_const page 404 (doc14-era id)
_DOC_PAGE_BASE = "https://tushare.pro/document/2"
# api → doc_id aligned with document/2 page body (sidebar menu labels can be wrong).
# doc14-era ids (e.g. top10_holders=50) often 404 on the live site after Tushare renumbered pages.
_API_CANONICAL_DOC_IDS: dict[str, int] = {
    "block_trade": 161,
    "broker_recommend": 267,
    "dividend": 103,
    "fina_mainbz": 81,
    "fund_company": 70,
    "fund_daily": 69,
    "fund_div": 71,
    "fund_portfolio": 121,
    "ggt_top10": 49,
    "hsgt_top10": 48,
    "index_dailybasic": 67,
    "index_member": 72,
    "index_weight": 66,
    "namechange": 100,
    "new_share": 123,
    "pledge_stat": 110,
    "pro_bar": 30,
    "repurchase": 124,
    "report_rc": 292,
    "stk_factor_pro": 328,
    "stk_holdernumber": 166,
    "stk_limit": 183,
    "stk_managers": 112,
    "stk_rewards": 194,
    "stock_company": 112,
    "top10_floatholders": 62,
    "top10_holders": 61,
}
# Bundled catalogs may carry stale api names after Tushare renumbered document/2 pages.
_BUNDLED_NON_AUTHORITATIVE_API_SOURCES = frozenset(
    {
        "tushare_stock_official_apis.json",
        "tushare_official_apis.json",
        "doc14_catalog",
        "tushare_api_by_doc_id.json",
    }
)
# Verified against tushare.pro interface pages (sidebar menu labels can be wrong).
_DOC_ID_OVERRIDES: dict[int, dict] = {
    26: {
        "api": "trade_cal",
        "label": "交易日历",
        "probe_category": "exchange_date_range",
        "category": "股票数据",
        "subcategory": "基础数据",
        "source": "doc_id_override",
    },
    28: {
        "api": "adj_factor",
        "label": "复权因子",
        "probe_category": "ts_code_date_range",
        "category": "股票数据",
        "subcategory": "行情数据",
        "source": "doc_id_override",
    },
    32: {
        "api": "daily_basic",
        "label": "每日指标",
        "probe_category": "ts_code_date_range",
        "category": "股票数据",
        "subcategory": "行情数据",
        "source": "doc_id_override",
    },
    214: {
        "api": "suspend_d",
        "label": "每日停复牌信息",
        "probe_category": "ts_code_date_range",
        "category": "股票数据",
        "subcategory": "行情数据",
        "source": "doc_id_override",
    },
    58: {
        "api": "pro",
        "label": "通用行情接口",
        "probe_category": "ts_code_date_range",
        "category": "股票数据",
        "subcategory": "行情数据",
        "source": "doc_id_override",
    },
}
_PROVIDERS = Path(__file__).resolve().parents[3] / "catalog" / "providers"
_API_BY_DOC_PATH = _PROVIDERS / "tushare_api_by_doc_id.json"
_DOC_PAGES_CACHE_PATH = _PROVIDERS / "tushare_doc_pages_cache.json"

# subcategory / category → probe template (document/2 menu structure)
_SUBCATEGORY_PROBE: dict[str, str] = {
    "基础数据": "list_basic",
    "行情数据": "ts_code_date_range",
    "财务数据": "period_financial",
    "参考数据": "ts_code",
    "特色数据": "ts_code_date_range",
    "两融及转融通": "trade_date",
    "资金流向数据": "ts_code_date_range",
    "打板专题数据": "trade_date",
    "概念板块": "list_limit",
    "指数": "index_daily",
    "基金": "list_limit",
    "期货": "ts_code_date_range",
    "现货": "trade_date",
    "期权": "ts_code_date_range",
    "债券": "list_limit",
    "外汇": "ts_code_date_range",
    "港股": "ts_code_date_range",
    "美股": "ts_code_date_range",
    "行业": "list_limit",
    "国内宏观": "list_limit",
    "国际宏观": "list_limit",
}

_CATEGORY_PROBE: dict[str, str] = {
    "股票数据": "list_limit",
    "指数专题": "index_daily",
    "公募基金": "list_limit",
    "期货数据": "ts_code_date_range",
    "现货数据": "trade_date",
    "期权数据": "ts_code_date_range",
    "债券专题": "list_limit",
    "外汇数据": "ts_code_date_range",
    "港股数据": "ts_code_date_range",
    "美股数据": "ts_code_date_range",
    "行业经济": "list_limit",
    "宏观经济": "list_limit",
    "大模型语料专题数据": "list_limit",
}


def get_api_canonical_doc_ids() -> dict[str, int]:
    """api → doc_id: wctapi specs override stale bundled hints."""
    from app.services.tia.scan.api_spec_store import build_api_to_doc_id_map

    merged = dict(_API_CANONICAL_DOC_IDS)
    merged.update(build_api_to_doc_id_map())
    return merged


def build_doc_page_url(doc_id: int | None) -> str | None:
    """Canonical Tushare document/2 URL for a doc_id."""
    if doc_id is None:
        return None
    return f"{_DOC_PAGE_BASE}?doc_id={int(doc_id)}"


def load_official_snapshot_doc_ids() -> frozenset[int]:
    """doc_ids present in bundled document/2 sidebar markdown snapshot."""
    snapshot = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "mcp_document2_sidebar.snapshot.md"
    )
    if not snapshot.is_file():
        return frozenset()
    return frozenset(int(m) for m in re.findall(r"doc_id=(\d+)", snapshot.read_text(encoding="utf-8")))


_API_NAME_PATTERNS: tuple[str, ...] = (
    r"接口[：:\s]*([a-z][a-z0-9_]*)",
    r"接口名称[：:\s]*([a-z][a-z0-9_]*)",
    r"API[：:\s]*([a-z][a-z0-9_]*)",
)


def parse_all_api_names_from_doc_text(text: str) -> list[str]:
    """Return every api name mentioned via 接口/接口名称/API lines (deduped, order preserved)."""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for pat in _API_NAME_PATTERNS:
        for match in re.finditer(pat, text, re.I):
            api = match.group(1).lower()
            if api not in seen:
                seen.add(api)
                out.append(api)
    return out


def parse_api_name_from_doc_text(text: str) -> str | None:
    apis = parse_all_api_names_from_doc_text(text)
    return apis[0] if apis else None


def parse_access_min_points_from_doc_text(text: str) -> int | None:
    """Parse interface **access** threshold from document/2 page body text."""
    from app.services.tia.scan.min_points_extractor import extract_access_min_points

    return extract_access_min_points(text)


def parse_min_points_from_doc_text(text: str) -> int | None:
    """Backward-compatible alias; prefers access threshold over frequency tier."""
    return parse_access_min_points_from_doc_text(text)


def infer_probe_category(
    *,
    category: str | None,
    subcategory: str | None,
    explicit: str | None = None,
) -> str:
    if explicit and explicit != "none":
        return explicit
    if subcategory and subcategory in _SUBCATEGORY_PROBE:
        return _SUBCATEGORY_PROBE[subcategory]
    if category and category in _CATEGORY_PROBE:
        return _CATEGORY_PROBE[category]
    return "list_limit"


def load_doc_pages_cache() -> dict[str, dict]:
    if not _DOC_PAGES_CACHE_PATH.is_file():
        return {}
    raw = json.loads(_DOC_PAGES_CACHE_PATH.read_text(encoding="utf-8"))
    return raw.get("pages", raw)


def _overlay_page_cache_on_registry(by_doc: dict[int, dict]) -> dict[int, dict]:
    """Apply doc-page-first min_points; bundled JSON hints are not authoritative."""
    from app.services.tia.scan.doc_points_resolver import resolve_min_points_from_doc_page

    page_cache = load_doc_pages_cache()
    if not page_cache:
        for row in by_doc.values():
            row.pop("min_points", None)
            row.pop("min_points_source", None)
        return by_doc
    out = {doc_id: dict(row) for doc_id, row in by_doc.items()}
    for doc_key, cached in page_cache.items():
        try:
            doc_id = int(doc_key)
        except ValueError:
            continue
        if doc_id in _DEPRECATED_DOC_IDS:
            continue
        row = dict(out.get(doc_id, {"doc_id": doc_id}))
        raw_text = cached.get("raw_text") or ""
        parsed_api = parse_api_name_from_doc_text(raw_text) if raw_text else None
        if parsed_api:
            row["api"] = parsed_api
        elif cached.get("api"):
            row["api"] = cached["api"]
        pts, pts_source = resolve_min_points_from_doc_page(doc_id, page_cache=page_cache)
        if pts is not None:
            row["min_points"] = int(pts)
            row["min_points_source"] = pts_source
        else:
            row.pop("min_points", None)
            row.pop("min_points_source", None)
        row["source"] = row.get("source") or "doc_pages_cache"
        out[doc_id] = row
    for doc_id, row in out.items():
        if str(doc_id) not in page_cache:
            pts, pts_source = resolve_min_points_from_doc_page(doc_id, page_cache=page_cache)
            if pts is not None:
                row["min_points"] = int(pts)
                row["min_points_source"] = pts_source
            else:
                row.pop("min_points", None)
                row.pop("min_points_source", None)
    return out


def resolve_min_points_for_doc_id(
    doc_id: int,
    *,
    api_by_doc: dict[int, dict] | None = None,
    page_cache: dict[str, dict] | None = None,
    sidebar_link: dict | None = None,
) -> tuple[int | None, str]:
    """Resolve min_points for one doc_id; document/2 page content is authoritative."""
    if doc_id in _DEPRECATED_DOC_IDS:
        return None, "deprecated"
    from app.services.tia.scan.doc_points_resolver import apply_doc_first_min_points

    lookup = api_by_doc or load_api_by_doc_id()
    meta = lookup.get(doc_id, {})
    sidebar_pts = sidebar_link.get("min_points") if sidebar_link else None
    bundled_pts = meta.get("min_points")
    return apply_doc_first_min_points(
        doc_id,
        page_cache=page_cache,
        sidebar_min_points=int(sidebar_pts) if sidebar_pts is not None else None,
        bundled_min_points=int(bundled_pts) if bundled_pts is not None else None,
    )


def _load_json(name: str) -> dict:
    path = _PROVIDERS / name
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_api_by_doc_id() -> dict[int, dict]:
    """Merge doc_id → api metadata from catalog, bundled JSON, page cache."""
    by_doc: dict[int, dict] = {}
    page_cache = load_doc_pages_cache()

    def _page_body_api(doc_id: int) -> str | None:
        cached = page_cache.get(str(doc_id), {})
        raw_text = cached.get("raw_text") or ""
        return parse_api_name_from_doc_text(raw_text) if raw_text else None

    def merge(doc_id: int, patch: dict) -> None:
        if doc_id in _DEPRECATED_DOC_IDS:
            return
        if doc_id in _DOC_ID_OVERRIDES:
            override = {k: v for k, v in _DOC_ID_OVERRIDES[doc_id].items() if k != "min_points"}
            patch = {**patch, **override}
        source = str(patch.get("source") or "")
        if source != "doc_pages_cache":
            patch = {k: v for k, v in patch.items() if k not in ("min_points", "min_points_source")}
            if "api" in patch and (
                source in _BUNDLED_NON_AUTHORITATIVE_API_SOURCES or _page_body_api(doc_id)
            ):
                patch = {k: v for k, v in patch.items() if k != "api"}
        prev = by_doc.get(doc_id, {})
        by_doc[doc_id] = {
            "doc_id": doc_id,
            "api": patch.get("api") or prev.get("api"),
            "label": patch.get("label") or prev.get("label"),
            "min_points": patch.get("min_points") if patch.get("min_points") is not None else prev.get("min_points"),
            "min_points_source": patch.get("min_points_source") or prev.get("min_points_source"),
            "probe_category": patch.get("probe_category") or prev.get("probe_category"),
            "category": patch.get("category") or prev.get("category"),
            "subcategory": patch.get("subcategory") or prev.get("subcategory"),
            "source": patch.get("source") or prev.get("source"),
        }

    for name in ("tushare_stock_official_apis.json", "tushare_official_apis.json"):
        for item in _load_json(name).get("apis", []):
            doc_id = item.get("doc_id")
            if doc_id is None:
                continue
            merge(
                int(doc_id),
                {
                    "api": item.get("api"),
                    "label": item.get("label"),
                    "min_points": item.get("min_points"),
                    "probe_category": item.get("probe_category"),
                    "source": name,
                },
            )

    for item in _load_json("tushare_doc14_catalog.json").get("entries", []):
        merge(
            int(item["doc_id"]),
            {
                "api": item.get("api"),
                "label": item.get("label"),
                "min_points": item.get("min_points"),
                "probe_category": item.get("probe_category"),
                "category": item.get("category"),
                "source": "doc14_catalog",
            },
        )

    for item in _load_json("tushare_document2_sidebar.json").get("entries", []):
        merge(
            int(item["doc_id"]),
            {
                "api": item.get("api"),
                "label": item.get("label"),
                "min_points": item.get("min_points"),
                "probe_category": item.get("probe_category"),
                "category": item.get("category"),
                "subcategory": item.get("subcategory"),
                "source": "document2_sidebar",
            },
        )

    for doc_key, cached in page_cache.items():
        try:
            doc_id = int(doc_key)
        except ValueError:
            continue
        raw_text = cached.get("raw_text") or ""
        page_api = parse_api_name_from_doc_text(raw_text) if raw_text else None
        patch: dict = {"source": "doc_pages_cache"}
        if page_api:
            patch["api"] = page_api
        elif cached.get("api"):
            patch["api"] = cached["api"]
        from app.services.tia.scan.doc_points_resolver import resolve_min_points_from_doc_page

        pts, pts_source = resolve_min_points_from_doc_page(doc_id, page_cache=page_cache)
        if pts is not None:
            patch["min_points"] = pts
            patch["min_points_source"] = pts_source
        merge(doc_id, patch)

    if _API_BY_DOC_PATH.is_file():
        for item in _load_json("tushare_api_by_doc_id.json").get("entries", []):
            row = dict(item)
            row["source"] = "tushare_api_by_doc_id.json"
            merge(int(item["doc_id"]), row)

    return _overlay_page_cache_on_registry(by_doc)


def load_api_by_doc_id() -> dict[int, dict]:
    if _API_BY_DOC_PATH.is_file():
        raw = json.loads(_API_BY_DOC_PATH.read_text(encoding="utf-8"))
        if isinstance(raw.get("by_doc_id"), dict):
            by_doc = {int(k): dict(v) for k, v in raw["by_doc_id"].items()}
        else:
            by_doc = {int(e["doc_id"]): dict(e) for e in raw.get("entries", [])}
    else:
        return build_api_by_doc_id()
    return _overlay_page_cache_on_registry(by_doc)


def _sidebar_entries_for_api(api_name: str) -> list[dict]:
    entries = [
        entry
        for entry in _load_json("tushare_document2_sidebar.json").get("entries", [])
        if entry.get("api") == api_name
    ]
    return sorted(entries, key=lambda row: int(row["doc_id"]), reverse=True)


def _sidebar_entry_for_doc_id(doc_id: int) -> dict | None:
    for entry in _load_json("tushare_document2_sidebar.json").get("entries", []):
        if int(entry.get("doc_id", -1)) == int(doc_id):
            return entry
    return None


def _pick_canonical_sidebar_entry(
    api_name: str,
    *,
    page_cache: dict[str, dict] | None = None,
) -> dict | None:
    forced_doc = get_api_canonical_doc_ids().get(api_name)
    if forced_doc is not None:
        entry = _sidebar_entry_for_doc_id(forced_doc)
        if entry is not None:
            return entry
        override = _DOC_ID_OVERRIDES.get(int(forced_doc), {})
        return {
            "doc_id": int(forced_doc),
            "label": override.get("label"),
            "category": override.get("category"),
            "subcategory": override.get("subcategory"),
            "api": api_name,
            "resolved": True,
        }

    override_doc = next(
        (doc_id for doc_id, meta in _DOC_ID_OVERRIDES.items() if meta.get("api") == api_name),
        None,
    )
    if override_doc is not None:
        for entry in _sidebar_entries_for_api(api_name):
            if int(entry["doc_id"]) == int(override_doc):
                return entry
        for entry in _load_json("tushare_document2_sidebar.json").get("entries", []):
            if int(entry.get("doc_id", -1)) == int(override_doc):
                return entry

    candidates = _sidebar_entries_for_api(api_name)
    if not candidates:
        return None
    cache = page_cache if page_cache is not None else load_doc_pages_cache()
    for entry in candidates:
        doc_id = int(entry["doc_id"])
        cached = cache.get(str(doc_id), {})
        cached_api = cached.get("api") or parse_api_name_from_doc_text(cached.get("raw_text") or "")
        if cached_api == api_name:
            return entry
    resolved = [entry for entry in candidates if entry.get("resolved")]
    return (resolved or candidates)[0]


def resolve_canonical_api_meta(api_name: str) -> dict | None:
    """Single source of truth: document/2 page body for doc_id / min_points."""
    from app.services.tia.constants import api_to_label
    from app.services.tia.scan.doc_points_api_resolver import (
        resolve_doc_id_for_api,
        resolve_min_points_for_api,
    )

    page_cache = load_doc_pages_cache()
    api_by_doc = load_api_by_doc_id()
    doc_id = resolve_doc_id_for_api(api_name, page_cache=page_cache)
    if doc_id is None:
        return _resolve_canonical_api_meta_fallback(api_name, page_cache=page_cache, api_by_doc=api_by_doc)

    sidebar_entry = _sidebar_entry_for_doc_id(doc_id) or _pick_canonical_sidebar_entry(
        api_name, page_cache=page_cache
    )
    enriched = (
        resolve_sidebar_entry(sidebar_entry, api_by_doc=api_by_doc, page_cache=page_cache)
        if sidebar_entry
        else {}
    )
    min_points, min_points_source = resolve_min_points_for_api(api_name, page_cache=page_cache)

    from app.services.tia.scan.api_spec_store import get_api_spec

    page_spec = get_api_spec(doc_id) if doc_id is not None else None
    page_api = page_spec.get("api") if page_spec else None
    if page_api and str(page_api).lower() != api_name.strip().lower():
        return {
            "doc_id": None,
            "api": api_name,
            "label": enriched.get("label") or api_to_label(api_name),
            "min_points": min_points,
            "min_points_source": min_points_source,
            "probe_category": enriched.get("probe_category"),
            "category": enriched.get("category"),
            "subcategory": enriched.get("subcategory"),
            "source": "document2_page_canonical",
            "doc_url": None,
            "doc_page_api": page_api,
        }

    return {
        "doc_id": doc_id,
        "api": api_name,
        "label": enriched.get("label") or api_to_label(api_name),
        "min_points": min_points,
        "min_points_source": min_points_source,
        "probe_category": enriched.get("probe_category"),
        "category": enriched.get("category"),
        "subcategory": enriched.get("subcategory"),
        "source": "document2_page_canonical",
        "doc_url": build_doc_page_url(doc_id),
    }


def _resolve_canonical_api_meta_fallback(
    api_name: str,
    *,
    page_cache: dict[str, dict],
    api_by_doc: dict[int, dict],
) -> dict | None:
    from app.services.tia.constants import api_to_label

    matches = [row for row in api_by_doc.values() if row.get("api") == api_name]
    if matches:
        best = max(matches, key=lambda row: int(row.get("doc_id") or 0))
        doc_id = int(best["doc_id"])
        min_points, min_points_source = resolve_min_points_for_doc_id(
            doc_id,
            api_by_doc=api_by_doc,
            page_cache=page_cache,
        )
        return {
            "doc_id": doc_id,
            "api": api_name,
            "label": best.get("label") or api_to_label(api_name),
            "min_points": min_points,
            "min_points_source": min_points_source,
            "doc_url": build_doc_page_url(doc_id),
        }

    for name in ("tushare_stock_official_apis.json", "tushare_official_apis.json"):
        for item in _load_json(name).get("apis", []):
            if item.get("api") == api_name:
                doc_id = item.get("doc_id")
                min_points = item.get("min_points")
                min_points_source = str(item.get("source") or name)
                if doc_id is not None:
                    resolved_pts, resolved_source = resolve_min_points_for_doc_id(
                        int(doc_id),
                        api_by_doc=api_by_doc,
                        page_cache=page_cache,
                    )
                    min_points = resolved_pts
                    min_points_source = resolved_source
                return {
                    "doc_id": doc_id,
                    "api": api_name,
                    "label": item.get("label"),
                    "min_points": min_points,
                    "min_points_source": min_points_source,
                    "probe_category": item.get("probe_category"),
                    "category": item.get("category"),
                    "source": name,
                    "doc_url": build_doc_page_url(int(doc_id)) if doc_id is not None else None,
                }
    return None


def resolve_api_meta(api_name: str) -> dict | None:
    """Lookup canonical doc metadata by api name."""
    return resolve_canonical_api_meta(api_name)


def resolve_sidebar_entry(
    link: dict,
    *,
    api_by_doc: dict[int, dict] | None = None,
    page_cache: dict[str, dict] | None = None,
) -> dict:
    """Enrich sidebar link with api/min_points/probe_category."""
    doc_id = int(link["doc_id"])
    if doc_id in _DEPRECATED_DOC_IDS:
        return {**link, "skipped": True}

    lookup = api_by_doc or load_api_by_doc_id()
    cache = page_cache if page_cache is not None else load_doc_pages_cache()
    override = _DOC_ID_OVERRIDES.get(doc_id, {})
    meta = {**lookup.get(doc_id, {}), **override}
    cached = cache.get(str(doc_id), {})

    raw_text = cached.get("raw_text") or ""
    page_api = parse_api_name_from_doc_text(raw_text) if raw_text else None
    api = page_api or cached.get("api") or override.get("api") or link.get("api") or meta.get("api")

    min_points, min_points_source = resolve_min_points_for_doc_id(
        doc_id,
        api_by_doc=lookup,
        page_cache=cache,
        sidebar_link=link,
    )

    category = link.get("category") or meta.get("category")
    subcategory = link.get("subcategory") or meta.get("subcategory")
    probe_category = infer_probe_category(
        category=category,
        subcategory=subcategory,
        explicit=link.get("probe_category") or meta.get("probe_category"),
    )

    return {
        "doc_id": doc_id,
        "label": link.get("label") or meta.get("label"),
        "category": category,
        "subcategory": subcategory,
        "api": api,
        "min_points": min_points,
        "min_points_source": min_points_source,
        "probe_category": probe_category,
        "doc_url": build_doc_page_url(doc_id),
        "resolved": bool(api),
    }
