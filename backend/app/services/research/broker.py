"""Simple long-only daily broker: next-open fill, equal weight, T+1."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd

from app.services.research.constants import INITIAL_EQUITY, MIN_SHARPE_DAYS
from app.services.research.signals import get_signal_fn


@dataclass
class Position:
    code: str
    shares: float
    entry_date: date
    entry_price: float


@dataclass
class BacktestResult:
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    kpi: dict[str, Any] = field(default_factory=dict)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if hasattr(value, "date") and callable(value.date):
        try:
            d = value.date()
            return d if isinstance(d, date) else None
        except Exception:
            return None
    if isinstance(value, str):
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _safe_px(value: Any) -> float | None:
    if value is None:
        return None
    try:
        px = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(px) or px <= 0:
        return None
    return px


def _bps_cost(notional: float, commission_bps: float, slippage_bps: float) -> float:
    return abs(notional) * (commission_bps + slippage_bps) / 10_000.0


def run_backtest(
    bars: dict[str, pd.DataFrame],
    *,
    signal_id: str,
    params: dict[str, Any],
    commission_bps: float = 5.0,
    slippage_bps: float = 5.0,
    max_positions: int = 5,
) -> BacktestResult:
    empty_kpi = {
        "total_return": 0.0,
        "max_drawdown": 0.0,
        "sharpe": None,
        "trade_count": 0,
        "sample_days": 0,
    }
    if not bars:
        return BacktestResult(kpi=empty_kpi)

    signal_fn = get_signal_fn(signal_id)
    annotated: dict[str, pd.DataFrame] = {}
    for code, df in bars.items():
        work = df.copy()
        if "volume" in work.columns:
            work = work[(work["volume"].isna()) | (work["volume"] > 0)]
        if work.empty:
            continue
        work = signal_fn(work, params)
        work["date"] = work["date"].map(_as_date)
        work = work.dropna(subset=["date"])
        annotated[code] = work

    all_dates = sorted({d for df in annotated.values() for d in df["date"].tolist() if d})
    if not all_dates:
        return BacktestResult(kpi=empty_kpi)

    by_date: dict[str, dict[date, Any]] = {}
    for code, df in annotated.items():
        mapping: dict[date, Any] = {}
        for row in df.itertuples(index=False):
            d = _as_date(row.date)
            if d is not None:
                mapping[d] = row
        by_date[code] = mapping

    cash = INITIAL_EQUITY
    positions: dict[str, Position] = {}
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    pending_buys: list[tuple[str, date]] = []
    pending_sells: set[str] = set()

    max_positions = max(1, int(max_positions))

    for i, dt in enumerate(all_dates):
        sold_today: set[str] = set()

        # 1) Execute pending sells at today's open
        for code in list(pending_sells):
            pos = positions.get(code)
            row = by_date.get(code, {}).get(dt)
            if pos is None:
                pending_sells.discard(code)
                continue
            px = _safe_px(None if row is None else getattr(row, "open", None))
            if px is None:
                continue
            pending_sells.discard(code)
            notional = pos.shares * px
            fee = _bps_cost(notional, commission_bps, slippage_bps)
            cash += notional - fee
            trades.append(
                {
                    "date": dt.isoformat(),
                    "code": code,
                    "side": "sell",
                    "price": round(px, 6),
                    "shares": round(pos.shares, 6),
                    "fee": round(fee, 8),
                }
            )
            del positions[code]
            sold_today.add(code)

        # 2) Execute pending buys at today's open (skip codes sold today — T+1)
        still_pending: list[tuple[str, date]] = []
        for code, sig_day in pending_buys:
            if code in positions:
                continue
            if code in sold_today or code in pending_sells:
                if i + 1 < len(all_dates):
                    still_pending.append((code, sig_day))
                continue
            if len(positions) >= max_positions:
                if i + 1 < len(all_dates):
                    still_pending.append((code, sig_day))
                continue
            row = by_date.get(code, {}).get(dt)
            px = _safe_px(None if row is None else getattr(row, "open", None))
            if px is None:
                if i + 1 < len(all_dates):
                    still_pending.append((code, sig_day))
                continue
            mtm = cash
            for p in positions.values():
                r = by_date.get(p.code, {}).get(dt)
                open_px = _safe_px(None if r is None else getattr(r, "open", None))
                mtm += p.shares * (open_px if open_px is not None else p.entry_price)
            target = mtm / max_positions
            if target <= 0 or cash < target * 0.5:
                if i + 1 < len(all_dates):
                    still_pending.append((code, sig_day))
                continue
            spend = min(cash, target)
            fee = _bps_cost(spend, commission_bps, slippage_bps)
            if spend <= fee:
                if i + 1 < len(all_dates):
                    still_pending.append((code, sig_day))
                continue
            shares = (spend - fee) / px
            cash -= spend
            positions[code] = Position(code=code, shares=shares, entry_date=dt, entry_price=px)
            trades.append(
                {
                    "date": dt.isoformat(),
                    "code": code,
                    "side": "buy",
                    "price": round(px, 6),
                    "shares": round(shares, 6),
                    "fee": round(fee, 8),
                }
            )
        pending_buys = still_pending

        # 3) Mark to market on close
        equity = cash
        for p in positions.values():
            r = by_date.get(p.code, {}).get(dt)
            close_px = _safe_px(None if r is None else getattr(r, "close", None))
            equity += p.shares * (close_px if close_px is not None else p.entry_price)
        equity_curve.append({"date": dt.isoformat(), "equity": round(float(equity), 8)})

        # 4) Schedule entries/exits from today's close → next open
        for code, df_map in by_date.items():
            row = df_map.get(dt)
            if row is None:
                continue
            if bool(getattr(row, "exit", False)) and code in positions:
                pending_sells.add(code)
            if (
                bool(getattr(row, "entry", False))
                and code not in positions
                and code not in pending_sells
            ):
                if not any(c == code for c, _ in pending_buys):
                    pending_buys.append((code, dt))

    # End flat: liquidate leftovers at last close
    if positions and all_dates:
        last = all_dates[-1]
        for code, pos in list(positions.items()):
            row = by_date.get(code, {}).get(last)
            px = _safe_px(None if row is None else getattr(row, "close", None))
            if px is None:
                px = _safe_px(None if row is None else getattr(row, "open", None))
            if px is None:
                px = pos.entry_price
            notional = pos.shares * px
            fee = _bps_cost(notional, commission_bps, slippage_bps)
            cash += notional - fee
            trades.append(
                {
                    "date": last.isoformat(),
                    "code": code,
                    "side": "sell",
                    "price": round(px, 6),
                    "shares": round(pos.shares, 6),
                    "fee": round(fee, 8),
                }
            )
            del positions[code]
        if equity_curve and equity_curve[-1]["date"] == last.isoformat():
            equity_curve[-1]["equity"] = round(float(cash), 8)
        else:
            equity_curve.append({"date": last.isoformat(), "equity": round(float(cash), 8)})

    return BacktestResult(
        equity_curve=equity_curve,
        trades=trades,
        kpi=_compute_kpi(equity_curve, trades),
    )


def _compute_kpi(equity_curve: list[dict[str, Any]], trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not equity_curve:
        return {
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe": None,
            "trade_count": 0,
            "sample_days": 0,
        }
    eq = [float(p["equity"]) for p in equity_curve]
    start = eq[0] if eq[0] else INITIAL_EQUITY
    total_return = (eq[-1] / start) - 1.0 if start else 0.0
    peak = eq[0]
    max_dd = 0.0
    for v in eq:
        peak = max(peak, v)
        if peak > 0:
            max_dd = min(max_dd, v / peak - 1.0)
    sharpe = None
    if len(eq) >= MIN_SHARPE_DAYS:
        rets = pd.Series(eq).pct_change().dropna()
        if len(rets) > 1 and float(rets.std()) > 1e-12:
            sharpe = float(rets.mean() / rets.std() * (252**0.5))
    return {
        "total_return": round(total_return, 6),
        "max_drawdown": round(max_dd, 6),
        "sharpe": None if sharpe is None else round(sharpe, 4),
        "trade_count": len(trades),
        "sample_days": len(eq),
    }
