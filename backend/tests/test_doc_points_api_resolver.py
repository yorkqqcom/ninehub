"""Tests for api ↔ doc_id ↔ min_points resolution from document/2 page body."""

from app.services.tia.scan.doc_points_api_resolver import (
    build_page_api_doc_map,
    parse_api_from_page_entry,
    resolve_doc_id_for_api,
    resolve_min_points_for_api,
    validate_api_points_binding,
)


def test_parse_api_from_page_entry_prefers_interface_line() -> None:
    entry = {
        "api": "index_weight",
        "raw_text": "接口：top10_holders 积分：需2000积分才可以调取",
    }
    assert parse_api_from_page_entry(entry) == "top10_holders"


def test_resolve_doc_id_uses_canonical_override() -> None:
    assert resolve_doc_id_for_api("index_weight") == 66
    assert resolve_doc_id_for_api("top10_holders") == 61
    assert resolve_doc_id_for_api("stk_factor_pro") == 146
    assert resolve_doc_id_for_api("pro_bar") == 30


def test_index_weight_and_top10_holders_points_differ() -> None:
    idx_pts, idx_src = resolve_min_points_for_api("index_weight")
    top_pts, top_src = resolve_min_points_for_api("top10_holders")
    assert idx_pts == 2000
    assert top_pts == 2000
    assert idx_src in ("doc_page_parsed", "doc_page_live")
    assert top_src in ("doc_page_parsed", "doc_page_live")


def test_stk_factor_pro_not_pro_bar_points() -> None:
    pts, source = resolve_min_points_for_api("stk_factor_pro")
    assert pts == 6000
    assert source in ("doc_page_parsed", "doc_page_live")


def test_resolve_min_points_api_doc_mismatch() -> None:
    cache = {
        "66": {
            "api": "index_weight",
            "raw_text": "接口：fut_daily 积分：需8000积分才可以调取",
            "min_points": 8000,
            "min_points_source": "doc_page_parsed",
            "fetcher": "mcp_live_compile",
        }
    }
    pts, source = resolve_min_points_for_api("index_weight", page_cache=cache)
    assert pts is None
    assert source == "api_doc_mismatch"


def test_build_page_api_doc_map_skips_error_rows() -> None:
    cache = {
        "61": {"raw_text": "接口：top10_holders 积分：需2000积分", "fetcher": "mcp_live_compile"},
        "bad": {"error": "404"},
    }
    mapping = build_page_api_doc_map(cache)
    assert mapping["top10_holders"] == 61
    assert "bad" not in mapping


def test_validate_api_points_binding_row() -> None:
    row = validate_api_points_binding("stock_hsgt")
    assert row["doc_id"] is not None
    assert row["page_api"] == "stock_hsgt"
    assert row["min_points"] == 6000
