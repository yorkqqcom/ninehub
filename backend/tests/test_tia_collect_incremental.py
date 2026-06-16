"""Incremental collect date resolution tests."""

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.sync_task import SyncTask
from app.models.task_run import TaskRun
from app.services.tasks.run_service import TaskRunService


def test_resolve_collect_dates_incremental() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    task = SyncTask(name="t", data_type="tia_daily", status="active")
    session.add(task)
    session.commit()

    session.add(
        TaskRun(
            task_id=task.id,
            status="success",
            rows_upserted=1,
            result_json={"collect_end_date": "2024-06-01"},
        )
    )
    session.commit()

    service = TaskRunService()
    start, end = service._resolve_collect_dates(session, task, "2010-01-01")
    assert start == date(2024, 6, 2)
    session.close()
