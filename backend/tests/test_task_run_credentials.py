"""Task run credential and failure semantics tests."""

import pytest

from app.models.data_source import DataSource
from app.models.sync_task import SyncTask
from app.models.task_run import TaskRun
from app.services.tasks.run_service import TaskRunService
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


def test_execute_run_fails_without_token(sync_session, monkeypatch) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "")
    from app.core.config import get_settings

    get_settings.cache_clear()

    task = SyncTask(name="t", data_type=TEST_DATA_TYPE, status="active")
    sync_session.add(task)
    sync_session.commit()

    run = TaskRunService().create_run_sync(sync_session, task.id)
    sync_session.commit()

    with pytest.raises(Exception) as exc_info:
        TaskRunService().execute_run_sync(sync_session, run.id)
    assert "Token" in str(exc_info.value) or "token" in str(exc_info.value).lower()

    sync_session.refresh(run)
    assert run.status == "failed"


def test_execute_run_uses_active_data_source(sync_session, monkeypatch) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "")
    from app.core.config import get_settings

    get_settings.cache_clear()

    source = DataSource(
        name="主 Tushare",
        provider="tushare",
        status="active",
        config={"token": "ds-token", "account_points": 120},
    )
    sync_session.add(source)
    sync_session.flush()

    task = SyncTask(name="t", data_type=TEST_DATA_TYPE, status="active")
    sync_session.add(task)
    sync_session.commit()

    run = TaskRunService().create_run_sync(sync_session, task.id)
    sync_session.commit()

    from unittest.mock import patch

    from app.sync.handlers import CollectResult

    with patch("app.services.tasks.run_service.SyncExecutor") as mock_exec, patch(
        "app.services.tasks.run_service.validate_points_for_data_type"
    ):
        mock_exec.return_value.run.return_value = CollectResult(
            rows_upserted=1, api_calls=1, message="ok"
        )
        TaskRunService().execute_run_sync(sync_session, run.id)

    sync_session.refresh(task)
    assert task.source_id == source.id


def test_build_sync_auth_extra_preserves_resolved_token() -> None:
    from app.services.tia.credentials_tdx import build_sync_auth_extra

    merged = build_sync_auth_extra(
        {
            "provider": "tushare",
            "token": "creds-token",
            "source_config": {"account_points": 2000},
        },
        {
            "session": object(),
            "table_name": "tushare_fina_audit",
        },
    )
    assert merged["token"] == "creds-token"
    assert merged["provider"] == "tushare"


def test_build_sync_auth_extra_prefers_extra_token() -> None:
    from app.services.tia.credentials_tdx import build_sync_auth_extra

    merged = build_sync_auth_extra(
        {"provider": "tushare", "source_config": {"account_points": 2000}},
        {"token": "extra-token"},
    )
    assert merged["token"] == "extra-token"
