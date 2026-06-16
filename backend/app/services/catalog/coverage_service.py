"""Read-only catalog vs official index coverage (no scan Job)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tia_override import TiaOverride
from app.schemas.catalog import CatalogCoverageItem, CatalogCoverageResponse, CatalogCoverageSummary
from app.services.tia.scan.index_loader import load_official_index
from app.services.tia.scan.orchestrator import TiaScanOrchestrator
from app.services.tia.scan.types import IndexScope, IndexSource, ScanOptions


class CatalogCoverageService:
    async def compute(
        self,
        session: AsyncSession,
        *,
        index_scope: IndexScope = "mixed",
        index_source: IndexSource = "auto",
        sample_limit: int = 30,
    ) -> CatalogCoverageResponse:
        options = ScanOptions(
            provider="tushare",
            mode="full",
            index_scope=index_scope,
            index_source=index_source,
            probe=False,
        )
        local_apis = await self._local_api_names(session)
        official_snapshot = load_official_index("tushare", options)
        official_apis = official_snapshot.api_names()
        diff = TiaScanOrchestrator._diff(local_apis, official_apis, official_snapshot)

        limit = max(1, min(sample_limit, 100))
        new_sample = [
            CatalogCoverageItem(api=api, reason="new_on_official")
            for api in diff.new_on_official[:limit]
        ]
        local_only_sample = [
            CatalogCoverageItem(api=api, reason="local_only")
            for api in diff.missing_from_official[:limit]
        ]
        unchanged_sample = [
            CatalogCoverageItem(api=api, reason="unchanged")
            for api in diff.unchanged[:limit]
        ]

        local_count = len(local_apis)
        official_count = len(official_apis)
        unchanged_count = len(diff.unchanged)
        coverage_pct = round(unchanged_count / official_count * 100, 1) if official_count else 0.0

        summary = CatalogCoverageSummary(
            local_count=local_count,
            official_count=official_count,
            unchanged_count=unchanged_count,
            new_on_official_count=len(diff.new_on_official),
            local_only_count=len(diff.missing_from_official),
            coverage_pct=coverage_pct,
            official_index_source=official_snapshot.source,
            official_index_scope=index_scope,
            official_index_total=official_snapshot.total,
        )
        return CatalogCoverageResponse(
            summary=summary,
            new_on_official_sample=new_sample,
            local_only_sample=local_only_sample,
            unchanged_sample=unchanged_sample,
        )

    @staticmethod
    async def _local_api_names(session: AsyncSession) -> list[str]:
        rows = await session.execute(select(TiaOverride.api_name))
        return sorted(rows.scalars().all())
