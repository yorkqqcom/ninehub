"""Tests for wctapi markdown doc spec parser."""

from app.services.tia.scan.doc_spec_parser import parse_wctapi_markdown

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


def test_parse_wctapi_markdown_daily() -> None:
    spec = parse_wctapi_markdown(27, DAILY_MD)
    assert spec is not None
    assert spec.api == "daily"
    assert spec.doc_id == 27
    assert len(spec.input_params) == 4
    assert spec.input_params[0].name == "ts_code"
    assert "open" in spec.output_fields
    assert len(spec.sample_codes) == 1
    assert "pro.daily" in spec.sample_codes[0]


def test_probe_spec_from_doc_daily() -> None:
    from app.services.tia.scan.probe_spec_from_doc import build_probe_spec_from_doc

    spec = parse_wctapi_markdown(27, DAILY_MD)
    assert spec is not None
    probe = build_probe_spec_from_doc(spec)
    assert probe["params"]["ts_code"] == "000001.SZ"
    assert "open" in probe["expected_fields"]
    assert probe["sample_codes"]
    assert probe["input_params"]


INCOME_MD = """
## 利润表
----
接口：income，可以通过**数据工具**调试和查看数据。
描述：获取上市公司财务利润表数据
积分：用户需要至少2000积分才可以调取

**输入参数**

名称 | 类型 | 必选 | 描述
---- | ----- | ---- | ----
ts_code | str | Y | 股票代码
period | str | N | 报告期

**输出参数**

名称 | 类型 | 默认显示 | 描述
--- | ---- | ---- | ----
ts_code | str | Y | TS代码
end_date | str | Y | 报告期
basic_eps | float | Y | 基本每股收益

**接口用法**

```python
pro = ts.pro_api()
df = pro.income(ts_code='600000.SH', period='20181231')
```
"""


def test_parse_wctapi_markdown_income() -> None:
    spec = parse_wctapi_markdown(33, INCOME_MD)
    assert spec is not None
    assert spec.api == "income"
    assert spec.min_points == 2000
    assert len(spec.input_params) == 2
    assert spec.input_params[0].required == "Y"
    assert "end_date" in spec.output_fields
    assert any("pro.income" in s for s in spec.sample_codes)
