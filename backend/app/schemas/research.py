"""Research / backtest API schemas."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field


class SignalParamDef(BaseModel):
    key: str
    label: str
    type: str
    default: Any = None
    min: Optional[float] = None
    max: Optional[float] = None
    options: Optional[list[str]] = None


class SignalDef(BaseModel):
    id: str
    name: str
    description: str
    params: list[SignalParamDef]


class BacktestCreateRequest(BaseModel):
    watchlist_id: Optional[int] = None
    codes: Optional[list[str]] = None
    start_date: date
    end_date: date
    signal_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    adjust: str = "qfq"
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    max_positions: int = 5


class BacktestEnqueueResponse(BaseModel):
    job_id: int
    message: str = "回测任务已入队"


class BacktestKpi(BaseModel):
    total_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: Optional[float] = None
    trade_count: int = 0
    sample_days: int = 0


class BacktestResultResponse(BaseModel):
    job_id: int
    status: str
    kpi: BacktestKpi
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    trades_preview: list[dict[str, Any]] = Field(default_factory=list)
    download_url: str
    params: Optional[dict[str, Any]] = None
    codes_loaded: Optional[list[str]] = None
    codes_requested: Optional[list[str]] = None
    codes_missing: Optional[list[str]] = None
