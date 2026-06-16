"""TIA collect strategy unit tests."""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.services.tia.sync_profiles import resolve_sync_profile
from app.services.tia.tia_data_loader import TiaDataLoader
from app.sync.handlers import SyncContext
from app.sync.tia_collect.base import StrategyContext
from app.sync.tia_collect.config import resolve_collect_config
from app.sync.tia_collect.date_range import DateRangeStrategy
from app.sync.tia_collect.exchange_date_range import ExchangeDateRangeStrategy
from app.sync.tia_collect.period import PeriodStrategy
from app.sync.tia_collect.router import get_collect_strategy
from app.sync.tia_collect.snapshot import SnapshotStrategy
from app.sync.tia_collect.trade_date import TradeDateStrategy
from app.sync.tia_collect.ts_code import TsCodeStrategy
from app.sync.tia_handler import TushareApiHandler


def _strategy_ctx(api_name: str, mode: str, session=None) -> StrategyContext:
    profile = resolve_sync_profile(api_name)
    schema = {
        "columns": [{"key": "stock_code", "type": "string"}, {"key": "trade_date", "type": "date"}],
        "unique_keys": ["stock_code", "trade_date"],
        "collect": {"max_codes_per_run": 2, "max_api_calls_per_run": 20},
    }
    sync_ctx = SyncContext(
        data_type=f"tia_{api_name}",
        source_id=0,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 5),
        extra={"token": "tok", "session": session, "stock_codes": ["000001.SZ", "600000.SH"]},
    )
    collector = MagicMock()
    return StrategyContext(
        api_name=api_name,
        data_type=f"tia_{api_name}",
        schema=schema,
        table_name=f"tia_{api_name}",
        sync_ctx=sync_ctx,
        collector=collector,
        loader=TiaDataLoader(),
        profile=profile,
        config=resolve_collect_config(schema, profile),
        session=session,
    )


def test_router_modes() -> None:
    assert isinstance(get_collect_strategy("snapshot"), SnapshotStrategy)
    assert isinstance(get_collect_strategy("date_range"), DateRangeStrategy)
    assert isinstance(get_collect_strategy("exchange_date_range"), ExchangeDateRangeStrategy)
    assert isinstance(get_collect_strategy("trade_date"), TradeDateStrategy)
    assert isinstance(get_collect_strategy("period"), PeriodStrategy)
    assert isinstance(get_collect_strategy("ts_code"), TsCodeStrategy)


@patch.object(TiaDataLoader, "upsert_dataframe", return_value=1)
def test_snapshot_strategy_calls_once(mock_upsert) -> None:
    ctx = _strategy_ctx("stock_basic", "snapshot")
    ctx.collector._call_pro.return_value = pd.DataFrame({"ts_code": ["000001.SZ"]})
    result = SnapshotStrategy().collect(ctx)
    assert ctx.collector._call_pro.call_count == 1
    assert result.api_calls == 1


def test_date_range_strategy_multiple_codes() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    ctx = _strategy_ctx("daily", "date_range", session=session)
    ctx.collector._call_pro.return_value = pd.DataFrame(
        {"ts_code": ["000001.SZ"], "trade_date": ["20240102"], "close": [1.0]}
    )
    with patch.object(TiaDataLoader, "upsert_dataframe", return_value=2) as mock_upsert:
        result = DateRangeStrategy().collect(ctx)
    assert ctx.collector._call_pro.call_count == 2
    assert result.api_calls == 2
    assert mock_upsert.called
    session.close()


def test_trade_date_strategy() -> None:
    ctx = _strategy_ctx("top_inst", "trade_date")
    ctx.collector._call_pro.return_value = pd.DataFrame(
        {"trade_date": ["20240102"], "ts_code": ["000001.SZ"]}
    )
    with patch.object(TiaDataLoader, "upsert_dataframe", return_value=1):
        result = TradeDateStrategy().collect(ctx)
    assert result.api_calls >= 1


def test_period_strategy() -> None:
    ctx = _strategy_ctx("income", "period")
    ctx.sync_ctx.start_date = date(2023, 12, 31)
    ctx.sync_ctx.end_date = date(2023, 12, 31)
    ctx.collector._call_pro.return_value = pd.DataFrame(
        {"ts_code": ["000001.SZ"], "end_date": ["20231231"], "revenue": [1.0]}
    )
    with patch.object(TiaDataLoader, "upsert_dataframe", return_value=1):
        result = PeriodStrategy().collect(ctx)
    assert result.api_calls == 8  # 2 codes x 4 quarters of 2023


def test_share_float_ts_code_profile() -> None:
    profile = resolve_sync_profile("share_float")
    assert profile.mode == "ts_code"


def test_handler_routes_by_profile() -> None:
    handler = TushareApiHandler(
        "daily",
        "tia_daily",
        {
            "columns": [{"key": "stock_code"}, {"key": "trade_date"}],
            "unique_keys": ["stock_code", "trade_date"],
            "collect": {"max_codes_per_run": 1, "max_api_calls_per_run": 5},
        },
    )
    ctx = SyncContext(
        data_type="tia_daily",
        source_id=0,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 2),
        extra={
            "token": "tok",
            "table_name": "tia_daily",
            "stock_codes": ["000001.SZ"],
        },
    )
    with patch.object(DateRangeStrategy, "collect") as mock_collect:
        mock_collect.return_value = type(
            "R",
            (),
            {
                "rows_upserted": 3,
                "api_calls": 1,
                "message": "ok",
                "detail_json": {"mode": "date_range"},
            },
        )()
        result = handler.collect(ctx)
    assert result.rows_upserted == 3
    assert result.detail_json["mode"] == "date_range"


def test_api_call_budget_raises() -> None:
    ctx = _strategy_ctx("daily", "date_range")
    ctx.config = resolve_collect_config(
        {"collect": {"max_codes_per_run": 100, "max_api_calls_per_run": 1}},
        ctx.profile,
    )
    with pytest.raises(Exception, match="exceeds limit"):
        DateRangeStrategy().collect(ctx)


@patch.object(TiaDataLoader, "upsert_dataframe", return_value=10)
def test_trade_cal_single_exchange_date_range_call(mock_upsert) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    ctx = _strategy_ctx("trade_cal", "exchange_date_range", session=session)
    ctx.collector._call_pro.return_value = pd.DataFrame(
        {
            "exchange": ["SSE"],
            "cal_date": ["20240102"],
            "is_open": [1],
        }
    )
    result = ExchangeDateRangeStrategy().collect(ctx)
    assert ctx.collector._call_pro.call_count == 1
    call_kwargs = ctx.collector._call_pro.call_args.kwargs
    assert call_kwargs["exchange"] == "SSE"
    assert call_kwargs["start_date"] == "20240102"
    assert call_kwargs["end_date"] == "20240105"
    assert result.api_calls == 1
    assert result.rows_upserted == 10
    session.close()
