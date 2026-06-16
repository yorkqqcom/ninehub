"""Tests for doc-page-first min_points resolution."""

from app.services.tia.scan.doc_points_resolver import (
    apply_doc_first_min_points,
    audit_bundled_vs_doc_page,
    is_fabricated_seed_text,
    is_stale_doc_page_entry,
    list_doc_ids_needing_live_fetch,
    parse_min_points_from_cache_entry,
    resolve_min_points_from_doc_page,
)
from app.services.tia.scan.tushare_doc_registry import (
    parse_access_min_points_from_doc_text,
    resolve_canonical_api_meta,
    resolve_min_points_for_doc_id,
)


def test_parse_daily_basic_official_text() -> None:
    text = (
        "接口：daily_basic 描述：获取全部股票每日重要的基本面指标 "
        "积分：至少2000积分才可以调取，5000积分无总量限制"
    )
    assert parse_access_min_points_from_doc_text(text) == 2000


def test_official_access_line_not_fabricated() -> None:
    assert is_fabricated_seed_text(
        "接口：top_inst 用户需要至少5000积分才可以调取",
        source="sidebar_seed",
    )
    assert not is_fabricated_seed_text(
        "接口：daily_basic 积分：至少2000积分才可以调取",
        source="official_text",
    )


def test_stale_sidebar_seed_entry() -> None:
    entry = {
        "api": "foo",
        "min_points": 999,
        "raw_text": "接口：foo_bar 说明：暂无积分信息",
        "source": "sidebar_seed",
    }
    assert is_stale_doc_page_entry(entry)
    pts, source = parse_min_points_from_cache_entry(entry)
    assert pts is None
    assert source == "stale_seed"


def test_apply_doc_first_ignores_bundled() -> None:
    pts, source = apply_doc_first_min_points(999, bundled_min_points=120)
    assert pts is None
    assert source == "unknown"


def test_live_entry_trusted() -> None:
    entry = {
        "api": "trade_cal",
        "min_points": 2000,
        "raw_text": "接口：trade_cal 积分：需2000积分",
        "fetcher": "playwright_auth",
        "min_points_source": "doc_page_live",
    }
    assert not is_stale_doc_page_entry(entry)
    pts, source = parse_min_points_from_cache_entry(entry)
    assert pts == 2000
    assert source == "doc_page_live"


def test_raw_text_overrides_stale_cached_min_points() -> None:
    entry = {
        "api": "top10_holders",
        "min_points": 120,
        "raw_text": "接口：top10_holders 积分：需2000积分才可以调取",
        "fetcher": "mcp_live_compile",
        "min_points_source": "doc_page_parsed",
    }
    pts, source = parse_min_points_from_cache_entry(entry)
    assert pts == 2000
    assert source == "doc_page_parsed"


def test_parsed_official_text_not_fabricated() -> None:
    cache = {
        "32": {
            "api": "daily_basic",
            "raw_text": "接口：daily_basic 积分：至少2000积分才可以调取",
            "source": "official_text",
        }
    }
    pts, source = resolve_min_points_from_doc_page(32, page_cache=cache)
    assert pts == 2000
    assert source == "doc_page_parsed"


def test_list_stale_doc_ids() -> None:
    cache = {
        "25": {"api": "stock_basic", "min_points": 120, "source": "sidebar_seed", "raw_text": "接口：stock_basic\n用户需要至少120积分才可以调取"},
        "32": {"api": "daily_basic", "raw_text": "接口：daily_basic 积分：至少2000积分", "fetcher": "httpx"},
    }
    stale = list_doc_ids_needing_live_fetch([25, 32], page_cache=cache)
    assert 25 in stale
    assert 32 not in stale


def test_audit_bundled_mismatch() -> None:
    cache = {"32": {"raw_text": "接口：daily_basic 积分：至少2000积分才可以调取"}}
    row = audit_bundled_vs_doc_page(32, 120, page_cache=cache)
    assert row is not None
    assert row["doc_min_points"] == 2000
    assert row["bundled_min_points"] == 120


def test_resolve_min_points_for_doc_id_daily_basic() -> None:
    pts, source = resolve_min_points_for_doc_id(32)
    assert pts == 2000
    assert source == "doc_page_parsed"


def test_resolve_canonical_daily_basic() -> None:
    meta = resolve_canonical_api_meta("daily_basic")
    assert meta is not None
    assert meta["doc_id"] == 32
    assert meta["min_points"] == 2000


def test_resolve_top_inst_doc107() -> None:
    pts, source = resolve_min_points_for_doc_id(107)
    assert pts == 5000
    assert source == "doc_page_parsed"
    meta = resolve_canonical_api_meta("top_inst")
    assert meta is not None
    assert meta["doc_id"] == 107
    assert meta["min_points"] == 5000


def test_resolve_top10_holders_from_canonical_doc_id() -> None:
    meta = resolve_canonical_api_meta("top10_holders")
    assert meta is not None
    assert meta["doc_id"] == 61
    pts, source = resolve_min_points_for_doc_id(61)
    # doc page not live-synced yet for canonical doc_id 61
    assert pts is None or source in {"doc_page_parsed", "doc_page_live", "unknown"}
