"""Tests for min_points extraction from document/2 page text."""

import json
from pathlib import Path

import pytest

from app.services.tia.scan.min_points_extractor import (
    extract_access_min_points,
    extract_from_doc_page,
    extract_points_section,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tushare_doc_min_points_corpus.json"


def _load_corpus_cases() -> list[dict]:
    if not _FIXTURE.is_file():
        return []
    raw = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return list(raw.get("cases", []))


@pytest.mark.parametrize(
    "case",
    _load_corpus_cases(),
    ids=lambda c: str(c.get("id", c.get("doc_id", "?"))),
)
def test_corpus_extract_access_min_points(case: dict) -> None:
    text = case["text"]
    expected = case.get("min_points")
    assert extract_access_min_points(text) == expected


def test_weekly_official_points_section() -> None:
    text = (
        "接口：weekly 描述：获取A股周线行情 "
        "积分：需2000积分以上才可以调取本接口，5000积分以上频次会更高 "
        "输入参数"
    )
    assert extract_access_min_points(text) == 2000
    section = extract_points_section(text)
    assert section is not None
    assert "5000" not in section or "频次" not in section


def test_top_inst_points_above_pattern() -> None:
    text = "积分：5000积分以上才可以调取，具体请参阅积分获取办法"
    assert extract_access_min_points(text) == 5000


def test_stock_basic_trial_vs_access() -> None:
    text = (
        "积分：120积分可以试用，每天10次请求 "
        "用户需要至少2000积分才可以调取，具体请参阅积分获取办法"
    )
    assert extract_access_min_points(text) == 2000


def test_income_user_need_at_least() -> None:
    text = "积分：用户需要至少2000积分才可以调取，具体请参阅积分获取办法"
    assert extract_access_min_points(text) == 2000


def test_ths_hot_no_points_section() -> None:
    text = "接口：ths_hot 描述：获取同花顺App热榜数据 输入参数"
    assert extract_access_min_points(text) is None


def test_stk_factor_pro_six_thousand_at_least() -> None:
    text = "积分：至少6000积分才可以调取"
    assert extract_access_min_points(text) == 6000


def test_eight_thousand_per_unit_patterns() -> None:
    assert extract_access_min_points("积分：8000积分/次") == 8000
    assert extract_access_min_points("积分：8000积分/分钟") == 8000
    assert extract_access_min_points("积分：8000积分/天") == 8000


def test_report_rc_thousand() -> None:
    text = "积分：用户需要至少1000积分才可以调取，具体请参阅积分获取办法"
    assert extract_access_min_points(text) == 1000


def test_generated_pattern_variants() -> None:
    """100 programmatic variants — access threshold must beat frequency tier."""
    templates = [
        ("积分：需{a}积分以上才可以调取本接口，{b}积分以上频次会更高", lambda a, b: a),
        ("积分：{a}积分以上才可以调取，具体请参阅积分获取办法", lambda a, b: a),
        ("积分：用户需要至少{a}积分才可以调取，{b}积分无总量限制", lambda a, b: a),
        ("用户需要至少{a}积分才可以调取，具体请参阅积分获取办法 频次限制 {b}积分", lambda a, b: a),
        ("积分：需{a}积分才可以调取，{b}积分以上频次会更高", lambda a, b: a),
        ("积分要求：{a}积分起，{b}以上可高频调取", lambda a, b: a),
    ]
    pairs = [(120, 2000), (2000, 5000), (600, 2000), (1000, 5000), (5000, 10000)]
    count = 0
    for tpl, fn in templates:
        for a, b in pairs:
            text = tpl.format(a=a, b=b)
            assert extract_access_min_points(text) == fn(a, b)
            count += 1
    assert count >= 30


def test_dividend_ji_hou_keyong() -> None:
    text = "积分：用户积1000积分后可用"
    assert extract_access_min_points(text) == 1000


def test_margin_jifen_qi() -> None:
    text = "积分：2000积分起"
    assert extract_access_min_points(text) == 2000


def test_express_diaoqu_yaoqiu() -> None:
    text = "调取要求大于120积分，且Finance接口勾选要求超过5000"
    assert extract_access_min_points(text) == 120


def test_stk_surv_normal_use() -> None:
    text = "积分：120积分正常使用"
    assert extract_access_min_points(text) == 120


def test_stock_hsgt_and_st_list() -> None:
    assert extract_access_min_points("积分：需6000积分才可以调取") == 6000
    assert extract_access_min_points("积分：需3000积分才可以调取") == 3000


def test_fina_mainbz_six_hundred() -> None:
    text = "积分：前10万名用户积分有600分"
    assert extract_access_min_points(text) == 600


def test_extract_from_doc_page_shape() -> None:
    parsed = extract_from_doc_page("积分：需2000积分以上才可以调取本接口，5000积分以上频次会更高")
    assert parsed["min_points"] == 2000
    assert "points_section" in parsed


def test_quanxian_section_disclosure_date() -> None:
    text = "接口：disclosure_date 权限：2000积分以上 输入参数"
    assert extract_access_min_points(text) == 2000


def test_vip_interface_no_numeric_threshold() -> None:
    assert extract_access_min_points("积分：本接口是VIP接口") is None


def test_vip_data_with_trial_not_threshold() -> None:
    from scripts._live_doc_plain_seeds import PLAIN_SEEDS

    assert extract_access_min_points(PLAIN_SEEDS[35]) is None
    assert extract_access_min_points(PLAIN_SEEDS[353]) is None
    assert extract_access_min_points(PLAIN_SEEDS[354]) is None
    assert extract_access_min_points(PLAIN_SEEDS[357]) is None


def test_index_member_1500() -> None:
    text = "权限：1500积分可调取"
    assert extract_access_min_points(text) == 1500
