"""Generic probe templates for APIs without explicit catalog probe specs."""

from __future__ import annotations

from typing import Any

# API 名 → 模板键；优先于 probe_category（如 trade_cal 不应使用 trade_date 模板）
API_PROBE_OVERRIDES: dict[str, str] = {
    "trade_cal": "trade_cal",
    "top_inst": "top_inst_detail",
}

PROBE_TEMPLATES: dict[str, dict[str, Any]] = {
    "ts_code_date_range": {
        "params": {
            "ts_code": "000001.SZ",
            "start_date": "20240102",
            "end_date": "20240105",
        },
        "expected_fields": [
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
        ],
    },
    "top_inst_detail": {
        "params": {
            "trade_date": "__LAST_TRADING_DAY__",
            "fields": "trade_date,ts_code,exalter,buy,sell,net_buy",
        },
        "expected_fields": ["trade_date", "ts_code", "exalter", "buy", "sell"],
    },
    "trade_date": {
        "params": {"trade_date": "__LAST_TRADING_DAY__"},
        "expected_fields": ["trade_date"],
    },
    # trade_cal 输出 cal_date，不是 trade_date
    "trade_cal": {
        "params": {"exchange": "SSE", "start_date": "20240101", "end_date": "20240105"},
        "expected_fields": ["exchange", "cal_date"],
    },
    # 通用交易所日历区间模板（与 trade_cal 同形态的新接口可复用）
    "exchange_date_range": {
        "params": {"exchange": "SSE", "start_date": "20240101", "end_date": "20240105"},
        "expected_fields": ["exchange", "cal_date"],
    },
    "ts_code": {
        "params": {"ts_code": "000001.SZ"},
        "expected_fields": ["ts_code"],
    },
    "period_financial": {
        "params": {"ts_code": "000001.SZ", "period": "20231231"},
        "expected_fields": ["ts_code", "end_date"],
    },
    "list_basic": {
        "params": {"exchange": "", "list_status": "L"},
        "expected_fields": ["ts_code"],
    },
    "list_limit": {
        "params": {"limit": 3},
        "expected_fields": [],
    },
    "index_daily": {
        "params": {
            "ts_code": "000001.SH",
            "start_date": "20240102",
            "end_date": "20240105",
        },
        "expected_fields": ["ts_code"],
    },
    "none": {
        "params": {},
        "expected_fields": [],
    },
}
