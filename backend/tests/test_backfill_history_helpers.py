"""Unit tests for run_backfill_history rotation helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_backfill_history.py"
_spec = importlib.util.spec_from_file_location("run_backfill_history_testmod", _SCRIPT)
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
assert _spec.loader is not None
_spec.loader.exec_module(_mod)


@pytest.mark.parametrize(
    "msg",
    [
        "Tushare disclosure_date failed: RetryError[...]",
        "Estimated 5000 API calls exceeds limit 200 for tushare_disclosure_date",
        "Tushare Token 未配置",
    ],
)
def test_collect_run_failed(msg: str) -> None:
    assert _mod._collect_run_failed(msg) is True


def test_collect_run_failed_empty_ok() -> None:
    assert _mod._collect_run_failed("") is False
    assert _mod._collect_run_failed("TIA express: empty response") is False


def test_finish_rotation_chunk_raises_on_retry_error() -> None:
    with pytest.raises(RuntimeError, match="failed"):
        _mod._finish_rotation_chunk(
            calls=0,
            msg="Tushare stock_basic failed: RetryError[...]",
        )


def test_schema_capped_overrides_budget() -> None:
    capped = _mod._schema_capped(
        {"collect": {"max_codes_per_run": 5000, "max_api_calls_per_run": 5000}},
        max_codes_per_run=200,
    )
    assert capped["collect"]["max_codes_per_run"] == 200
    assert capped["collect"]["max_api_calls_per_run"] == _mod.API_BUDGET


@pytest.mark.parametrize(
    ("from_chunk", "per_chunk", "expected"),
    [
        (1, 100, 0),
        (21, 100, 2000),
        (2, 100, 100),
    ],
)
def test_chunk_start_offset(from_chunk: int, per_chunk: int, expected: int) -> None:
    assert _mod._chunk_start_offset(from_chunk, per_chunk) == expected


def test_effective_mode_daily_uses_trade_date() -> None:
    from app.services.workflow.collect_batch import DAILY_BATCH_MODE_OVERRIDES

    assert DAILY_BATCH_MODE_OVERRIDES["daily"] == "trade_date"
    assert _mod._effective_mode("daily", {}) == "trade_date"


def test_period_rotation_plan_full_vs_gap_budget() -> None:
    """Estimate and backfill must share the same period span for codes/run."""
    from datetime import date

    from app.sync.tia_collect.period import _periods_in_range

    full = len(_periods_in_range(date(2024, 1, 1), date(2026, 6, 23)))
    gap = len(_periods_in_range(date(2024, 1, 1), date(2024, 4, 2)))
    assert full == 12
    assert gap == 4
    assert _mod.API_BUDGET // full == 16
    assert _mod.API_BUDGET // gap == 50
    # ~5529 listed stocks: full span needs 346 rotations, gap resume needs 111.
    assert (5529 + 16 - 1) // 16 == 346
    assert (5529 + 50 - 1) // 50 == 111
