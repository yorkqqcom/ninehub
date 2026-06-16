"""Tests for Tushare doc page fetcher."""

import httpx
import pytest
import respx

from app.services.tia.scan.tushare_doc_page_fetcher import (
    fetch_doc_page,
    html_to_plain_text,
    parse_doc_page_content,
)


SAMPLE_HTML = """
<html><body>
<h2>利润表</h2>
<p>接口：income</p>
<p>用户需要至少600积分才可以调取，具体请参阅积分获取办法</p>
<p>频次限制：每分钟最多调用10次，每天总量不限制</p>
<p>2000积分</p>
</body></html>
"""


def test_html_to_plain_text_strips_tags() -> None:
    text = html_to_plain_text(SAMPLE_HTML)
    assert "income" in text
    assert "<p>" not in text


def test_parse_doc_page_content_access_threshold() -> None:
    text = html_to_plain_text(SAMPLE_HTML)
    parsed = parse_doc_page_content(text)
    assert parsed["api"] == "income"
    assert parsed["min_points"] == 600


@respx.mock
def test_fetch_doc_page_parses_api_and_points() -> None:
    respx.get("https://tushare.pro/document/2").mock(
        return_value=httpx.Response(200, text=SAMPLE_HTML)
    )
    result = fetch_doc_page(33)
    assert result["api"] == "income"
    assert result["min_points"] == 600
    assert result["http_status"] == 200
