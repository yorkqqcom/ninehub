"""Respx-backed TIA collect handler tests for catalog APIs."""

from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from app.sync.handlers import SyncContext
from app.sync.tia_handler import TushareApiHandler


@pytest.mark.parametrize(
    ("api_name", "mode"),
    [
        ("stock_basic", "snapshot"),
        ("daily", "date_range"),
        ("income", "period"),
        ("top_inst", "trade_date"),
        ("share_float", "ts_code"),
    ],
)
def test_catalog_handler_modes(api_name: str, mode: str) -> None:
    schema = {
        "columns": [{"key": "stock_code", "type": "string"}, {"key": "trade_date", "type": "date"}],
        "unique_keys": ["stock_code", "trade_date"],
        "collect": {"max_codes_per_run": 1, "max_api_calls_per_run": 10},
    }
    handler = TushareApiHandler(api_name, f"tia_{api_name}", schema)
    ctx = SyncContext(
        data_type=f"tia_{api_name}",
        source_id=0,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 3),
        extra={
            "token": "test-token",
            "table_name": f"tia_{api_name}",
            "stock_codes": ["000001.SZ"],
        },
    )
    fake_df = pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240102"], "close": [10.0]})

    with patch("app.services.collectors.tushare.TushareCollector._call_pro", return_value=fake_df):
        with patch("app.services.tia.tia_data_loader.TiaDataLoader.upsert_dataframe", return_value=1):
            result = handler.collect(ctx)

    assert result.api_calls >= 1
    assert result.detail_json is not None
    assert result.detail_json.get("mode") == mode
