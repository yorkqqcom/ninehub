"""TIA Celery tasks."""

from app.core.database import SyncSessionLocal
from app.services.tia.activation_service import TiaActivationService
from app.services.tia.service import TIAService
from app.tasks.celery_app import celery_app


@celery_app.task(name="ninehub.run_tia_scan")
def run_tia_scan_task(job_id: int, scan_options: dict | None = None) -> dict:
    service = TIAService()
    session = SyncSessionLocal()
    try:
        from app.services.tia.scan.types import ScanOptions

        opts = ScanOptions.from_dict(scan_options) if scan_options else None
        result = service.execute_scan_sync(session, job_id, options=opts)
        return {"job_id": job_id, "status": "success", "result": result}
    except Exception as exc:
        return {"job_id": job_id, "status": "failed", "error": str(exc)}
    finally:
        session.close()


@celery_app.task(name="ninehub.run_tia_doc_pages_sync")
def run_tia_doc_pages_sync_task(job_id: int, sync_options: dict | None = None) -> dict:
    service = TIAService()
    session = SyncSessionLocal()
    try:
        from app.services.tia.scan.doc_pages_sync_types import DocPagesSyncOptions

        opts = DocPagesSyncOptions.from_dict(sync_options) if sync_options else None
        result = service.execute_doc_pages_sync_sync(session, job_id, options=opts)
        return {"job_id": job_id, "status": "success", "result": result}
    except Exception as exc:
        return {"job_id": job_id, "status": "failed", "error": str(exc)}
    finally:
        session.close()


@celery_app.task(name="ninehub.run_tia_activate")
def run_tia_activate_task(job_id: int) -> dict:
    service = TiaActivationService()
    session = SyncSessionLocal()
    try:
        result = service.execute_activation_sync(session, job_id)
        return {"job_id": job_id, "status": "success", "result": result}
    except Exception as exc:
        from app.services.platform.job_service import PlatformJobService

        try:
            PlatformJobService().update_sync(
                session,
                job_id,
                status="failed",
                progress=100,
                message="Activation failed",
                error=str(exc),
            )
            session.commit()
        except Exception:
            session.rollback()
        return {"job_id": job_id, "status": "failed", "error": str(exc)}
    finally:
        session.close()
