"""Sync handler registry tests."""

from datetime import date

import pytest

from app.core.exceptions import NotFoundError, ValidationError
from app.sync.executor import SyncExecutor
from app.sync.handlers import CollectResult, DATA_TYPE_HANDLERS, SyncContext, SyncHandler, register_handler


class _StubHandler(SyncHandler):
    def collect(self, ctx: SyncContext) -> CollectResult:
        return CollectResult(rows_upserted=1, api_calls=1, message="ok")


def test_executor_missing_handler() -> None:
    executor = SyncExecutor()
    ctx = SyncContext(
        data_type="missing",
        source_id=1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
    )
    with pytest.raises(NotFoundError):
        executor.run(ctx)


def test_executor_invalid_dates() -> None:
    register_handler("test_type", _StubHandler())
    executor = SyncExecutor()
    ctx = SyncContext(
        data_type="test_type",
        source_id=1,
        start_date=date(2024, 2, 1),
        end_date=date(2024, 1, 1),
    )
    with pytest.raises(ValidationError):
        executor.run(ctx)


def test_executor_success() -> None:
    register_handler("test_type_ok", _StubHandler())
    executor = SyncExecutor()
    ctx = SyncContext(
        data_type="test_type_ok",
        source_id=1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 2),
    )
    result = executor.run(ctx)
    assert result.rows_upserted == 1
    DATA_TYPE_HANDLERS.pop("test_type_ok", None)
