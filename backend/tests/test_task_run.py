"""Tests for task run SyncExecutor integration."""

from unittest.mock import patch

import pytest

from app.models.sync_task import SyncTask
from app.models.task_run import TaskRun  # noqa: F401
from app.services.tasks.run_service import TaskRunService
from app.sync.handlers import CollectResult
from catalog_test_support import TEST_DATA_TYPE


@pytest.fixture
def sync_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.base import Base

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def test_execute_run_sync_calls_executor(sync_session) -> None:
    task = SyncTask(name="test", data_type=TEST_DATA_TYPE, status="active")
    sync_session.add(task)
    sync_session.commit()

    run = TaskRunService().create_run_sync(sync_session, task.id)
    sync_session.commit()

    mock_result = CollectResult(rows_upserted=5, message="ok")
    with patch("app.services.tasks.run_service.SyncExecutor") as mock_exec, patch(
        "app.services.tasks.run_service.validate_points_for_data_type"
    ), patch(
        "app.services.tasks.run_service.resolve_collect_source_credentials",
        return_value={
            "token": "test-token",
            "provider": "tushare",
            "source_config": {"account_points": 120},
            "source_id": 1,
        },
    ):
        mock_exec.return_value.run.return_value = mock_result
        updated = TaskRunService().execute_run_sync(sync_session, run.id)

    assert updated.status == "success"
    assert updated.rows_upserted == 5
    assert updated.message == "ok"


def test_upstream_dependency_blocks(sync_session) -> None:
    upstream = SyncTask(name="up", data_type=TEST_DATA_TYPE, status="active")
    sync_session.add(upstream)
    sync_session.flush()
    downstream = SyncTask(
        name="down",
        data_type=TEST_DATA_TYPE,
        status="active",
        upstream_task_id=upstream.id,
    )
    sync_session.add(downstream)
    sync_session.commit()

    run = TaskRunService().create_run_sync(sync_session, downstream.id)
    sync_session.commit()

    with pytest.raises(Exception) as exc_info:
        TaskRunService().execute_run_sync(sync_session, run.id)
    assert "上游" in str(exc_info.value)


def test_tushare_rate_limiter() -> None:
    from app.services.collectors.tushare import max_calls_per_minute, wait_before_pro_call

    assert max_calls_per_minute() >= 50
    wait_before_pro_call()  # should not raise
