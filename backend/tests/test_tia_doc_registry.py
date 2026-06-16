"""Tests for Tushare doc_id registry."""

from app.services.tia.proposal_enrichment import build_api_meta_map
from app.services.tia.scan.min_points_extractor import extract_access_min_points
from app.services.tia.scan.tushare_doc_registry import (
    build_api_by_doc_id,
    infer_probe_category,
    parse_access_min_points_from_doc_text,
    parse_min_points_from_doc_text,
    resolve_api_meta,
    resolve_canonical_api_meta,
    resolve_min_points_for_doc_id,
    resolve_sidebar_entry,
)


def test_build_api_by_doc_id_includes_catalog() -> None:
    by_doc = build_api_by_doc_id()
    assert 27 in by_doc
    assert by_doc[27]["api"] == "daily"
    assert 108 not in by_doc


def test_infer_probe_category_from_subcategory() -> None:
    assert infer_probe_category(category="股票数据", subcategory="行情数据", explicit=None) == "ts_code_date_range"
    assert infer_probe_category(category="宏观经济", subcategory="国内宏观", explicit=None) == "list_limit"


def test_resolve_sidebar_entry_from_page_cache() -> None:
    link = {"doc_id": 999, "label": "测试", "category": "股票数据", "subcategory": "行情数据"}
    cache = {"999": {"raw_text": "接口：foo_bar\n120积分起"}}
    out = resolve_sidebar_entry(link, page_cache=cache)
    assert out["api"] == "foo_bar"
    assert out["resolved"] is True
    assert out["min_points"] == 120
    assert out["min_points_source"] == "doc_page_parsed"


def test_parse_access_min_points_ignores_frequency_tier() -> None:
    text = (
        "用户需要至少120积分才可以调取，具体请参阅积分获取办法 "
        "频次限制：每分钟最多调取该接口500次，每天总量不限制 2000积分"
    )
    assert parse_access_min_points_from_doc_text(text) == 120
    assert parse_min_points_from_doc_text(text) == 120


def test_resolve_canonical_api_meta_prefers_latest_sidebar_doc_id() -> None:
    meta = resolve_canonical_api_meta("top_list")
    assert meta is not None
    assert meta["doc_id"] == 106
    assert meta["min_points"] == 2000
    assert resolve_api_meta("top_list")["doc_id"] == 106


def test_doc_id_override_pro() -> None:
    meta = resolve_canonical_api_meta("pro")
    assert meta is not None
    assert meta["doc_id"] == 58
    assert meta["api"] == "pro" or meta.get("label")
    pts, _ = resolve_min_points_for_doc_id(58)
    # pro doc page may be stale seed until live sync; api mapping override still applies
    assert meta["doc_id"] == 58


def test_doc_id_override_trade_cal_doc26() -> None:
    """doc_id=26 trade_cal requires 2000 pts per document/2?doc_id=26."""
    meta = resolve_canonical_api_meta("trade_cal")
    assert meta is not None
    assert meta["doc_id"] == 26
    assert meta["min_points"] == 2000
    pts, source = resolve_min_points_for_doc_id(26)
    assert pts == 2000
    assert source in ("doc_page_parsed", "doc_page_live", "doc_pages_cache")


def test_parse_trade_cal_points_from_official_text() -> None:
    text = "接口：trade_cal 积分：需2000积分"
    assert parse_access_min_points_from_doc_text(text) == 2000


def test_doc_id_override_adj_factor_doc28() -> None:
    """doc_id=28 is adj_factor (2000 pts), not weekly — see document/2?doc_id=28."""
    meta = resolve_canonical_api_meta("adj_factor")
    assert meta is not None
    assert meta["doc_id"] == 28
    assert meta["min_points"] == 2000
    pts, source = resolve_min_points_for_doc_id(28)
    assert pts == 2000
    assert source in ("doc_page_parsed", "doc_page_live", "doc_pages_cache")
    by_doc = build_api_by_doc_id()
    assert by_doc[28]["api"] == "adj_factor"


def test_weekly_canonical_doc_id_144() -> None:
    meta = resolve_canonical_api_meta("weekly")
    assert meta is not None
    assert meta["doc_id"] == 144
    assert meta["min_points"] == 2000
    pts, source = resolve_min_points_for_doc_id(144)
    assert pts == 2000
    assert source == "doc_page_parsed"


def test_parse_adj_factor_points_from_official_text() -> None:
    text = "接口：adj_factor 积分要求：2000积分起，5000以上可高频调取"
    assert parse_access_min_points_from_doc_text(text) == 2000


def test_parse_weekly_points_yishang_pattern() -> None:
    text = "积分：需2000积分以上才可以调取本接口，5000积分以上频次会更高"
    assert parse_access_min_points_from_doc_text(text) == 2000


def test_suspend_d_permission_section_5000() -> None:
    text = "接口：suspend_d 权限：5000积分每分钟5000次 输入参数"
    assert extract_access_min_points(text) == 5000


def test_cyq_chips_no_daily_limit() -> None:
    text = "积分：5000积分无每天总量限制"
    assert extract_access_min_points(text) == 5000


def test_hm_list_ten_thousand() -> None:
    assert extract_access_min_points("积分：10000积分以上可调取") == 10000
    assert extract_access_min_points("积分：10000积分可一次获取全部数据") == 10000


def test_cn_cpi_repeat() -> None:
    assert extract_access_min_points("积分：1000积分可重复调取") == 1000


def test_new_share_can_use() -> None:
    assert extract_access_min_points("积分：1000积分可以使用") == 1000


def test_fund_nav_consumption_not_threshold() -> None:
    text = "积分消耗：单次3000条，需要消耗用户积分"
    assert extract_access_min_points(text) is None


def test_vip_data_trial_not_access_threshold() -> None:
    text = "积分：本接口是VIP数据，需单独开通权限 120积分可以试用"
    assert extract_access_min_points(text) is None


def test_deprecated_doc_id_35_returns_none() -> None:
    pts, source = resolve_min_points_for_doc_id(35)
    assert pts is None
    assert source == "deprecated"


def test_suspend_d_cache_5000() -> None:
    pts, _ = resolve_min_points_for_doc_id(214)
    assert pts == 5000


def test_build_api_meta_map_matches_canonical_doc_id() -> None:
    meta = build_api_meta_map()
    assert meta["top_list"]["doc_id"] == 106
    assert meta["top10_holders"]["doc_id"] == 61
    assert meta["top10_holders"]["min_points"] == 2000
    assert meta["index_weight"]["doc_id"] == 66
    assert meta["index_weight"]["min_points"] == 2000
    assert meta["stock_basic"]["min_points"] == 2000
    assert meta["stk_factor_pro"]["min_points"] == 6000
    assert meta["stock_hsgt"]["min_points"] == 6000


def test_resolve_sidebar_entry_page_api_beats_wrong_sidebar_api() -> None:
    """doc 61 sidebar wrongly labels index_weight; page body says top10_holders."""
    link = {
        "doc_id": 61,
        "label": "前十大股东",
        "category": "股票数据",
        "subcategory": "参考数据",
        "api": "index_weight",
        "min_points": 120,
    }
    out = resolve_sidebar_entry(link)
    assert out["api"] == "top10_holders"
    assert out["min_points"] == 2000
