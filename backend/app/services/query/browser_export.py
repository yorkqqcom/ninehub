"""Browser export — sync CSV/XLSX and async platform jobs."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.schemas.query_browser import BrowserExecuteRequest, BrowserExportRequest, BrowserExportResponse
from app.services.platform.job_service import PlatformJobService
from app.services.query.browser_query import BrowserQueryService


class BrowserExportService:
    def __init__(self) -> None:
        self._query = BrowserQueryService()
        self._jobs = PlatformJobService()

    def _export_dir(self) -> Path:
        settings = get_settings()
        base = Path(settings.static_dir)
        export = base / settings.export_dir
        export.mkdir(parents=True, exist_ok=True)
        return export

    async def export(
        self,
        session: AsyncSession,
        body: BrowserExportRequest,
        user_id: int | None,
    ) -> BrowserExportResponse:
        snapshot_at = datetime.now(timezone.utc)
        if body.async_job:
            job = await self._jobs.create(
                session,
                job_type="browser_export",
                created_by_id=user_id,
            )
            await self._jobs.update(
                session,
                job.id,
                message="browser export queued",
                result_json={
                    "snapshot_at": snapshot_at.isoformat(),
                    "payload": body.query.model_dump(mode="json"),
                    "format": body.format,
                },
            )
            await session.commit()
            from app.tasks.browser_tasks import run_browser_export_task
            from app.tasks.dispatch import dispatch_task

            dispatch_task(run_browser_export_task, job.id)
            return BrowserExportResponse(
                job_id=job.id,
                snapshot_at=snapshot_at,
                message="导出任务已入队（近似快照）",
            )

        file_bytes, _ = await self._build_file(session, body.query, user_id, body.format)
        if body.format == "xlsx":
            token = uuid.uuid4().hex
            path = self._export_dir() / f"browser_sync_{token}.xlsx"
            path.write_bytes(file_bytes)
            return BrowserExportResponse(
                download_url=f"/api/v1/query/browser/exports/sync/{token}/download",
                snapshot_at=snapshot_at,
                message="同步 xlsx 导出完成",
            )
        return BrowserExportResponse(
            content=file_bytes.decode("utf-8"),
            snapshot_at=snapshot_at,
            message="同步导出完成",
        )

    async def _build_file(
        self,
        session: AsyncSession,
        query: BrowserExecuteRequest,
        user_id: int | None,
        fmt: str,
    ) -> tuple[bytes, list[str]]:
        export_query = query.model_copy(
            update={"skip": 0, "limit": 2000, "include_aggregations": False}
        )
        result = await self._query.execute(session, export_query, user_id)
        col_ids = [c.id for c in result.columns]
        if fmt == "xlsx":
            return self._to_xlsx(result.items, col_ids, result.columns), col_ids
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=col_ids, extrasaction="ignore")
        writer.writeheader()
        for row in result.items:
            writer.writerow({k: row.get(k, "") for k in col_ids})
        return buf.getvalue().encode("utf-8"), col_ids

    def _to_xlsx(self, items: list[dict], col_ids: list[str], columns) -> bytes:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "export"
        headers = [next((c.label for c in columns if c.id == cid), cid) for cid in col_ids]
        ws.append(headers)
        for row in items:
            ws.append([row.get(k, "") for k in col_ids])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    def _write_export_file(self, job_id: int, data: bytes, fmt: str) -> str:
        ext = "xlsx" if fmt == "xlsx" else "csv"
        path = self._export_dir() / f"browser_{job_id}.{ext}"
        path.write_bytes(data)
        return f"/api/v1/query/browser/exports/{job_id}/download"

    async def run_job_export(self, session: AsyncSession, job_id: int) -> dict:
        job = await self._jobs.get(session, job_id)
        payload = (job.result_json or {}).get("payload") or {}
        fmt = (job.result_json or {}).get("format") or "csv"
        query = BrowserExecuteRequest.model_validate(payload)
        full_query = query.model_copy(
            update={"skip": 0, "limit": 8000, "include_aggregations": False}
        )
        file_bytes, col_ids = await self._build_file(
            session, full_query, job.created_by_id, fmt
        )
        download_url = self._write_export_file(job_id, file_bytes, fmt)
        await self._jobs.update(
            session,
            job_id,
            status="success",
            progress=100,
            message="export done",
            result_json={
                **(job.result_json or {}),
                "row_bytes": len(file_bytes),
                "row_count": len(col_ids),
                "download_url": download_url,
                "format": fmt,
            },
        )
        await session.commit()
        return {"job_id": job_id, "status": "success", "download_url": download_url}

    def read_export_file(self, job_id: int) -> tuple[bytes, str] | None:
        export_dir = self._export_dir()
        for ext, mime in (("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"), ("csv", "text/csv")):
            path = export_dir / f"browser_{job_id}.{ext}"
            if path.is_file():
                return path.read_bytes(), mime
        return None

    def read_sync_export_file(self, token: str) -> tuple[bytes, str] | None:
        path = self._export_dir() / f"browser_sync_{token}.xlsx"
        if not path.is_file():
            return None
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        return path.read_bytes(), mime
