"""Route sync profile mode to collect strategy."""

from __future__ import annotations

from app.sync.tia_collect.base import CollectStrategy
from app.sync.tia_collect.date_range import DateRangeStrategy
from app.sync.tia_collect.exchange_date_range import ExchangeDateRangeStrategy
from app.sync.tia_collect.generic import GenericStrategy
from app.sync.tia_collect.period import PeriodStrategy
from app.sync.tia_collect.snapshot import SnapshotStrategy
from app.sync.tia_collect.tdx_strategies import (
    TdxConceptSnapshotStrategy,
    TdxNetworkBarStrategy,
    TdxVipdocImportStrategy,
)
from app.sync.tia_collect.trade_date import TradeDateStrategy
from app.sync.tia_collect.ts_code import TsCodeStrategy

_STRATEGIES: dict[str, CollectStrategy] = {
    "snapshot": SnapshotStrategy(),
    "date_range": DateRangeStrategy(),
    "exchange_date_range": ExchangeDateRangeStrategy(),
    "trade_date": TradeDateStrategy(),
    "period": PeriodStrategy(),
    "ts_code": TsCodeStrategy(),
    "generic": GenericStrategy(),
    "file_import": TdxVipdocImportStrategy(),
    "tdx_network": TdxNetworkBarStrategy(),
    "tdx_concept_snapshot": TdxConceptSnapshotStrategy(),
}


def get_collect_strategy(mode: str) -> CollectStrategy:
    return _STRATEGIES.get(mode, _STRATEGIES["generic"])
