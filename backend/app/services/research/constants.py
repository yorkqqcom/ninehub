"""Backtest hard limits (phase-1 freeze)."""

from __future__ import annotations

import re

MAX_UNIVERSE = 200
MAX_YEARS = 5
MIN_SHARPE_DAYS = 20
INITIAL_EQUITY = 1.0
TRADE_PREVIEW_LIMIT = 100
JOB_TYPE = "backtest_run"
SYMBOL_RE = re.compile(r"^\d{6}\.(SH|SZ)$")
OHLC_KEYS = ("open", "high", "low", "close")
