"""Tests for canonical Tushare doc_id / doc_url resolution (document/2 sidebar)."""

from app.services.tia.proposal_enrichment import build_api_meta_map, enrich_proposal
from app.services.tia.scan.doc_points_api_resolver import parse_api_from_page_entry
from app.services.tia.scan.tushare_doc_registry import (
    get_api_canonical_doc_ids,
    build_doc_page_url,
    load_doc_pages_cache,
    load_official_snapshot_doc_ids,
    resolve_canonical_api_meta,
)
from app.models.tia_proposal import TiaProposal


def test_build_doc_page_url() -> None:
    assert build_doc_page_url(32) == "https://tushare.pro/document/2?doc_id=32"
    assert build_doc_page_url(None) is None


def test_canonical_doc_ids_in_official_snapshot() -> None:
    """Canonical doc_id must appear in sidebar snapshot or match a cached page body."""
    official = load_official_snapshot_doc_ids()
    cache = load_doc_pages_cache()
    assert official
    skip_without_page = frozenset({"pro_bar"})
    for api, doc_id in get_api_canonical_doc_ids().items():
        if api in skip_without_page:
            continue
        doc_id = int(doc_id)
        in_snapshot = doc_id in official
        cached = cache.get(str(doc_id), {})
        page_api = parse_api_from_page_entry(cached)
        assert in_snapshot or page_api == api, (
            f"{api} doc_id={doc_id} missing from sidebar snapshot and page cache"
        )


def test_renumbered_apis_use_wctapi_doc_ids() -> None:
    """doc_id / doc_url must match wctapi specs (not stale sidebar api fields)."""
    cases = {
        "top10_holders": 61,
        "top10_floatholders": 62,
        "report_rc": 292,
        "stock_company": 112,
        "stk_limit": 183,
        "stk_rewards": 194,
        "stk_factor_pro": 328,
        "broker_recommend": 267,
        "hsgt_top10": 48,
        "ggt_top10": 49,
        "fina_indicator": 79,
        "index_basic": 94,
        "fund_portfolio": 121,
        "limit_step": 356,
    }
    for api, expected in cases.items():
        meta = resolve_canonical_api_meta(api)
        assert meta is not None, api
        assert meta["doc_id"] == expected, api
        assert meta["doc_url"] == build_doc_page_url(expected)


def test_proposal_enrichment_doc_url_for_top10_holders() -> None:
    meta = enrich_proposal(TiaProposal(api_name="top10_holders", status="pending"))
    assert meta["doc_id"] == 61
    assert meta["doc_url"] == "https://tushare.pro/document/2?doc_id=61"


def test_build_api_meta_map_includes_doc_url() -> None:
    meta = build_api_meta_map().get("dividend")
    assert meta is not None
    assert meta["doc_id"] == 103
    assert "doc_id=103" in (meta.get("doc_url") or "")
