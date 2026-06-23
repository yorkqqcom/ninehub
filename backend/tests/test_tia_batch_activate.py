"""Tests for sequential TIA batch L3 activation dispatch."""

from unittest.mock import MagicMock, patch

from app.tasks.tia_tasks import dispatch_tia_activate_jobs, run_tia_batch_activate_task


def test_dispatch_single_job_uses_activate_task() -> None:
    with patch("app.tasks.dispatch.dispatch_task") as mock_dispatch:
        dispatch_tia_activate_jobs([42])
    mock_dispatch.assert_called_once()
    task, job_id = mock_dispatch.call_args[0]
    assert job_id == 42
    assert task.name == "ninehub.run_tia_activate"


def test_dispatch_multiple_jobs_uses_batch_task() -> None:
    with patch("app.tasks.dispatch.dispatch_task") as mock_dispatch:
        dispatch_tia_activate_jobs([1, 2, 3])
    mock_dispatch.assert_called_once()
    task, job_ids = mock_dispatch.call_args[0]
    assert job_ids == [1, 2, 3]
    assert task.name == "ninehub.run_tia_batch_activate"


def test_batch_activate_task_runs_sequentially_and_continues_on_failure() -> None:
    service = MagicMock()
    service.execute_activation_sync.side_effect = [None, RuntimeError("boom"), None]

    with patch("app.tasks.tia_tasks.TiaActivationService", return_value=service), patch(
        "app.tasks.tia_tasks.SyncSessionLocal", return_value=MagicMock()
    ):
        result = run_tia_batch_activate_task([10, 11, 12])

    assert result["processed"] == 3
    assert result["succeeded"] == 2
    assert service.execute_activation_sync.call_count == 3
