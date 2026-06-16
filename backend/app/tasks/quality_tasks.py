"""Quality check Celery task (G-05)."""

from datetime import date

from app.core.database import SyncSessionLocal
from app.services.platform.job_service import PlatformJobService
from app.services.quality.service import QualityService
from app.services.trading_calendar.service import is_trading_day
from app.tasks.celery_app import celery_app


@celery_app.task(name="ninehub.run_quality_check")
def run_quality_check_task(
    data_type: str | None = None,
    stock_code: str | None = None,
    job_id: int | None = None,
) -> dict:
    if not is_trading_day(date.today()):
        result = {"status": "skipped", "reason": "non_trading_day"}
        if job_id is not None:
            session = SyncSessionLocal()
            try:
                PlatformJobService().update_sync(
                    session,
                    job_id,
                    status="success",
                    progress=100,
                    message="非交易日，已跳过",
                    result_json=result,
                )
                session.commit()
            finally:
                session.close()
        return result

    session = SyncSessionLocal()
    jobs = PlatformJobService()
    try:
        if job_id is not None:
            jobs.update_sync(
                session,
                job_id,
                status="running",
                progress=10,
                message="质检运行中",
            )
            session.commit()
        service = QualityService()
        result = service.run_check_sync(session, data_type=data_type, stock_code=stock_code)
        session.commit()
        payload = {
            "status": "success",
            "reports_created": result.reports_created,
            "message": result.message,
            "alerts_sent": result.alerts_sent,
        }
        if job_id is not None:
            jobs.update_sync(
                session,
                job_id,
                status="success",
                progress=100,
                message=result.message,
                result_json=payload,
            )
            session.commit()
        return payload
    except Exception as exc:
        session.rollback()
        if job_id is not None:
            jobs.update_sync(
                session,
                job_id,
                status="failed",
                progress=0,
                message="质检失败",
                error=str(exc),
            )
            session.commit()
        return {"status": "failed", "error": str(exc)}
    finally:
        session.close()
