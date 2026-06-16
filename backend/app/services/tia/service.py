"""TIA governance: catalog scan with platform_jobs progress."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.tia_override import TiaOverride
from app.models.platform_job import PlatformJob
from app.services.platform.job_service import PlatformJobService
from app.services.tia.doc_pages_sync_service import DocPagesSyncService
from app.services.tia.scan.orchestrator import TiaScanOrchestrator
from app.services.tia.scan.doc_pages_sync_types import DocPagesSyncOptions
from app.services.tia.scan.types import ScanOptions


class TIAService:
    def __init__(self) -> None:
        self._job_service = PlatformJobService()
        self._orchestrator = TiaScanOrchestrator(job_service=self._job_service)
        self._doc_pages_sync = DocPagesSyncService()

    async def start_scan(
        self,
        session: AsyncSession,
        created_by_id: int | None = None,
        options: ScanOptions | None = None,
    ) -> int:
        opts = options or ScanOptions()
        job = await self._job_service.create(session, "tia_scan", created_by_id=created_by_id)
        await self._job_service.update(
            session,
            job.id,
            result_json={"scan_options": opts.to_dict()},
        )
        await session.commit()
        return job.id

    def execute_scan_sync(
        self,
        session: Session,
        job_id: int,
        options: ScanOptions | None = None,
    ) -> dict[str, Any]:
        """Run scan in Celery worker; updates platform_jobs progress at each stage."""
        job = session.get(PlatformJob, job_id)
        if job is None:
            from app.core.exceptions import NotFoundError
            raise NotFoundError(f"Job {job_id} not found")
        stored = (job.result_json or {}).get("scan_options") if job.result_json else None
        # Task kwargs beat DB snapshot (avoids inline-dispatch read race)
        opts = options or ScanOptions.from_dict(stored)

        def progress(pct: int, message: str) -> None:
            self._job_service.update_sync(
                session,
                job_id,
                status="running",
                progress=pct,
                message=message,
            )

        try:
            result = self._orchestrator.run(session, job_id, opts, progress)
            self._job_service.update_sync(
                session,
                job_id,
                status="success",
                progress=100,
                message=result.get("scan_message"),
                result_json=result,
            )
            session.commit()
            return result
        except Exception as exc:
            session.rollback()
            self._job_service.update_sync(
                session,
                job_id,
                status="failed",
                progress=0,
                message="Scan failed",
                error=str(exc),
            )
            session.commit()
            raise

    async def start_doc_pages_sync(
        self,
        session: AsyncSession,
        created_by_id: int | None = None,
        options: DocPagesSyncOptions | None = None,
    ) -> int:
        opts = options or DocPagesSyncOptions()
        job = await self._job_service.create(
            session, "tia_doc_pages_sync", created_by_id=created_by_id
        )
        await self._job_service.update(
            session,
            job.id,
            result_json={"sync_options": opts.to_dict()},
        )
        await session.commit()
        return job.id

    def execute_doc_pages_sync_sync(
        self,
        session: Session,
        job_id: int,
        options: DocPagesSyncOptions | None = None,
    ) -> dict[str, Any]:
        from app.core.exceptions import NotFoundError, ValidationError

        job = session.get(PlatformJob, job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        stored = (job.result_json or {}).get("sync_options") if job.result_json else None
        opts = options or DocPagesSyncOptions.from_dict(stored)

        def progress(pct: int, message: str) -> None:
            self._job_service.update_sync(
                session,
                job_id,
                status="running",
                progress=pct,
                message=message,
            )

        try:
            result = self._doc_pages_sync.run(session, opts, progress)
            if (
                not opts.dry_run
                and result.get("merge_stats", {}).get("with_points", 0) == 0
                and result.get("doc_ids_total", 0) > 0
            ):
                raise ValidationError("未成功抓取任何接口页，请检查 Playwright 登录态配置")
            self._job_service.update_sync(
                session,
                job_id,
                status="success",
                progress=100,
                message=result.get("sync_message") or "Doc pages sync complete",
                result_json=result,
            )
            session.commit()
            return result
        except Exception as exc:
            session.rollback()
            self._job_service.update_sync(
                session,
                job_id,
                status="failed",
                progress=0,
                message="Doc pages sync failed",
                error=str(exc),
            )
            session.commit()
            raise

    async def start_points_audit(
        self,
        session: AsyncSession,
        created_by_id: int | None = None,
    ) -> int:
        from sqlalchemy import select

        from app.services.tia.scan.tushare_doc_catalog import (
            load_document2_sidebar_index,
            load_document2_sidebar_raw,
        )
        from app.services.tia.scan.tushare_doc_registry import (
            resolve_canonical_api_meta,
            resolve_min_points_for_doc_id,
        )

        job = await self._job_service.create(session, "tia_audit", created_by_id=created_by_id)
        await self._job_service.update(
            session,
            job.id,
            status="running",
            progress=10,
            message="Loading document/2 sidebar vs overrides",
        )
        await session.commit()

        sidebar_snap = load_document2_sidebar_index(index_scope="mixed")
        sidebar_map = sidebar_snap.as_map()
        sidebar_apis = set(sidebar_map.keys())
        result = await session.execute(select(TiaOverride))
        overrides = {o.api_name: o for o in result.scalars().all()}
        override_apis = set(overrides.keys())

        sidebar_raw = load_document2_sidebar_raw()
        sidebar_gaps = sorted(override_apis - sidebar_apis)
        points_mismatches: list[dict[str, object]] = []
        doc_url_mismatches: list[dict[str, object]] = []

        for api in sorted(override_apis):
            override = overrides[api]
            override_pts = override.min_points
            canonical = resolve_canonical_api_meta(api) or {}
            doc_id = canonical.get("doc_id")
            official_doc_pts: int | None = None
            if doc_id is not None:
                resolved_pts, pts_source = resolve_min_points_for_doc_id(int(doc_id))
                official_doc_pts = resolved_pts
                pts_source_label = pts_source
            else:
                entry = sidebar_map.get(api)
                official_doc_pts = entry.min_points if entry else None
                pts_source_label = "document2_sidebar"
            expected_url = canonical.get("doc_url") or (
                f"https://tushare.pro/document/2?doc_id={doc_id}" if doc_id else None
            )
            if official_doc_pts is not None and override_pts != official_doc_pts:
                points_mismatches.append(
                    {
                        "api": api,
                        "override_min_points": override_pts,
                        "official_doc_min_points": official_doc_pts,
                        "doc_id": doc_id,
                        "min_points_source": pts_source_label,
                        "note": "override vs interface doc page",
                    }
                )
            if expected_url and override.doc_url and override.doc_url != expected_url:
                doc_url_mismatches.append(
                    {
                        "api": api,
                        "override_doc_url": override.doc_url,
                        "canonical_doc_url": expected_url,
                        "doc_id": doc_id,
                        "note": "override doc_url vs canonical doc_id",
                    }
                )

        audit_result = {
            "override_count": len(override_apis),
            "doc14_count": len(sidebar_apis),
            "doc14_index_source": sidebar_snap.source,
            "sidebar_link_count": sidebar_raw.get("sidebar_link_count"),
            "doc14_gaps": sidebar_gaps,
            "points_mismatches": points_mismatches,
            "doc_url_mismatches": doc_url_mismatches,
            "sources": ["document2_sidebar", "doc_pages_cache", "tia_overrides"],
            "deprecated_sources": ["doc108_summary", "tushare_catalog"],
        }
        await self._job_service.update(
            session,
            job.id,
            status="success",
            progress=100,
            message=(
                f"Audit: {len(sidebar_gaps)} sidebar gaps, "
                f"{len(points_mismatches)} point mismatches, "
                f"{len(doc_url_mismatches)} doc_url mismatches"
            ),
            result_json=audit_result,
        )
        await session.commit()
        return job.id
