"""Bundled Tushare API output fields — catalog preview fallback only.

L3 审批激活建表以 Preflight 实盘探针 ``actual_fields`` 为准；本注册表仅在
``live_probe=false`` 或数据标准预览时补充模板字段，不驱动 DDL。
"""

from __future__ import annotations

# OHLCV bar interfaces (daily / weekly / monthly / adj_factor / suspend_d …)
_TS_CODE_DATE_RANGE_OUTPUT: list[str] = [
    "ts_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "change",
    "pct_chg",
    "vol",
    "amount",
]

API_OUTPUT_FIELDS: dict[str, list[str]] = {
    "daily": list(_TS_CODE_DATE_RANGE_OUTPUT),
    "weekly": list(_TS_CODE_DATE_RANGE_OUTPUT),
    "monthly": list(_TS_CODE_DATE_RANGE_OUTPUT),
    "adj_factor": ["ts_code", "trade_date", "adj_factor"],
    "suspend_d": ["ts_code", "trade_date", "suspend_timing", "suspend_type"],
    "trade_cal": ["exchange", "cal_date", "is_open", "pretrade_date"],
    "daily_basic": [
        "ts_code",
        "trade_date",
        "close",
        "turnover_rate",
        "turnover_rate_f",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "ps",
        "ps_ttm",
        "dv_ratio",
        "dv_ttm",
        "total_share",
        "float_share",
        "free_share",
        "total_mv",
        "circ_mv",
    ],
}


def registry_output_fields(api_name: str) -> list[str]:
    return list(API_OUTPUT_FIELDS.get(api_name) or [])
