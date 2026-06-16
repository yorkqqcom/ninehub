"""Tests for doc spec fetcher with respx."""

import httpx
import pytest
import respx

from app.services.tia.scan.doc_spec_fetcher import fetch_doc_spec

DAILY_MD = """
## A股日线行情
----
接口：daily，可以通过**数据工具**调试和查看数据
描述：获取股票行情数据

**输入参数**

名称 | 类型 | 必选 | 描述
---- | ----- | ---- | ----
ts_code | str | N | 股票代码
trade_date | str | N | 交易日期（YYYYMMDD）
start_date | str | N | 开始日期(YYYYMMDD)
end_date | str | N | 结束日期(YYYYMMDD)

**输出参数**

名称 | 类型 | 描述
--- | ---- | ----
ts_code | str | 股票代码
trade_date | str | 交易日期
open | float | 开盘价
close | float | 收盘价
vol | float | 成交量

**接口示例**

```python
pro = ts.pro_api()
df = pro.daily(ts_code='000001.SZ', start_date='20180701', end_date='20180718')
```
"""


@respx.mock
def test_fetch_doc_spec_parses_wctapi_md() -> None:
    respx.get("https://tushare.pro/wctapi/documents/27.md").mock(
        return_value=httpx.Response(200, text=DAILY_MD)
    )
    row = fetch_doc_spec(27)
    assert row["api"] == "daily"
    assert len(row["output_fields"]) >= 4
    assert row["fetcher"] == "wctapi_md"


def test_validate_api_via_sdk_invalid_name(respx_mock: respx.MockRouter) -> None:
    from app.services.tia.scan.tushare_sdk_validate import validate_api_via_sdk

    respx_mock.post("http://api.waditu.com/dataapi/totally_invalid_api_xyz").mock(
        return_value=httpx.Response(
            200,
            json={"code": 40101, "msg": "请指定正确的接口名", "data": None},
        )
    )
    result = validate_api_via_sdk("fake-token", "totally_invalid_api_xyz", {})
    assert result["sdk_valid"] is False


def test_resolve_probe_spec_prefers_doc_cache(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.tia.scan import api_spec_store
    from app.services.tia.scan.probe_planner import resolve_probe_spec
    from app.services.tia.scan.types import OfficialApiEntry

    cache_path = tmp_path / "specs.json"
    monkeypatch.setattr(api_spec_store, "_SPECS_CACHE_PATH", cache_path)
    api_spec_store.save_api_specs_cache(
        {
            "27": {
                "doc_id": 27,
                "api": "daily",
                "doc_url": "https://tushare.pro/document/2?doc_id=27",
                "doc_md_url": "https://tushare.pro/wctapi/documents/27.md",
                "probe_spec": {
                    "params": {"ts_code": "000001.SZ", "start_date": "20240102", "end_date": "20240105"},
                    "expected_fields": ["ts_code", "trade_date", "open", "close"],
                },
            }
        }
    )

    spec, source, _ = resolve_probe_spec(
        "daily",
        OfficialApiEntry(api="daily", doc_id=27),
    )
    assert source == "doc_spec_cache"
    assert spec is not None
    assert "open" in spec["expected_fields"]
