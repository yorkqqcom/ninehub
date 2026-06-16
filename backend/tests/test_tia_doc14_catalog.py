"""Tests for doc_id=14 official catalog loader."""

import pytest

from app.services.tia.scan.tushare_doc_catalog import (
    load_doc14_catalog_raw,
    load_doc14_official_index,
    load_document2_sidebar_index,
    load_document2_sidebar_raw,
    merge_entry,
    parse_api_name_from_doc_text,
    parse_min_points_from_doc_text,
)
from app.services.tia.scan.tushare_sidebar_parser import parse_sidebar_markdown


def test_doc14_catalog_excludes_deprecated_108() -> None:
    raw = load_doc14_catalog_raw()
    doc_ids = {e["doc_id"] for e in raw.get("entries", [])}
    assert 108 not in doc_ids
    assert 108 in raw.get("deprecated_doc_ids", [])


def test_load_document2_sidebar_stock_a() -> None:
    raw = load_document2_sidebar_raw()
    if not raw.get("entries"):
        pytest.skip("document2 sidebar json not generated")
    snap = load_document2_sidebar_index(index_scope="stock_a")
    assert snap.source == "document2_sidebar"
    assert snap.total >= 30


def test_parse_sidebar_markdown_categories() -> None:
    md = """## 股票数据
### 行情数据
[历史日线](https://tushare.pro/document/2?doc_id=27)
## 指数专题
[指数基本信息](https://tushare.pro/document/2?doc_id=94)
"""
    links = parse_sidebar_markdown(md)
    assert len(links) == 2
    assert links[0]["category"] == "股票数据"
    assert links[0]["subcategory"] == "行情数据"
    assert links[1]["category"] == "指数专题"


def test_load_doc14_stock_a_index() -> None:
    snap = load_doc14_official_index(index_scope="stock_a")
    assert snap.source == "doc14_catalog"
    assert snap.total >= 60
    assert "daily" in snap.api_names()
    assert "stock_basic" in snap.api_names()
    # macro-only apis from mixed bundled should not appear in stock_a scope
    assert "cn_gdp" not in snap.api_names()


def test_load_doc14_mixed_includes_macro() -> None:
    snap = load_doc14_official_index(index_scope="mixed")
    assert snap.total >= 75
    assert "cn_gdp" in snap.api_names() or "index_basic" in snap.api_names()


def test_merge_entry_uses_page_cache() -> None:
    entry = {"doc_id": 27, "label": "历史日线", "category": "行情数据"}
    page_cache = {
        "27": {
            "raw_text": "接口：daily\n积分：120起",
        }
    }
    merged = merge_entry(entry, page_cache)
    assert merged is not None
    assert merged.api == "daily"
    assert merged.min_points == 120


def test_merge_entry_skips_doc_108() -> None:
    assert merge_entry({"doc_id": 108, "api": "ignored"}, {}) is None


def test_parse_doc_text_helpers() -> None:
    text = "接口：income\n需要至少600积分才能调取"
    assert parse_api_name_from_doc_text(text) == "income"
    assert parse_min_points_from_doc_text(text) == 600
