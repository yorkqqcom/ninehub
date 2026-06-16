"""Catalog list service for UI."""

from app.catalog.registry import get_data_type_entry, list_data_types, list_domains
from app.core.exceptions import NotFoundError, ValidationError
from app.schemas.catalog import (
    BrowseDomainCount,
    BrowseTypeSummary,
    DataBrowseResponse,
    DataTypeListItem,
    DataTypeListResponse,
    DomainItem,
)
from app.services.catalog_query import CatalogQueryService


class CatalogService:
    _query = CatalogQueryService()

    async def list_data_types(
        self,
        session=None,
        domain: str | None = None,
        browse_only: bool = False,
        q: str | None = None,
        include_stats: bool = False,
    ) -> DataTypeListResponse:
        entries = list_data_types(domain=domain)
        if browse_only:
            entries = [e for e in entries if e.browse_enabled and e.is_activated]
        if q:
            needle = q.strip().lower()
            entries = [
                e
                for e in entries
                if needle in e.data_type.lower()
                or needle in e.label.lower()
                or (e.table_name and needle in e.table_name.lower())
            ]

        domain_labels = dict(list_domains())
        items: list[DataTypeListItem] = []
        for e in entries:
            row_count = None
            if include_stats and session is not None and e.browse_enabled and e.table_name:
                try:
                    row_count = await self._query.count_rows(session, e.data_type, {})
                except (ValueError, OSError):
                    row_count = None
            items.append(
                DataTypeListItem(
                    data_type=e.data_type,
                    domain=e.domain,
                    label=e.label,
                    is_activated=e.is_activated,
                    browse_enabled=e.browse_enabled,
                    min_points=e.min_points,
                    chart_type=e.chart_type,
                    table_name=e.table_name,
                    filters=e.filters,
                    row_count=row_count,
                )
            )

        domains = [DomainItem(key=k, label=v) for k, v in list_domains()]
        summary = None
        if browse_only:
            all_browse = list_data_types()
            all_browse = [e for e in all_browse if e.browse_enabled and e.is_activated]
            domain_counts: dict[str, int] = {}
            for e in all_browse:
                domain_counts[e.domain] = domain_counts.get(e.domain, 0) + 1
            summary = BrowseTypeSummary(
                total=len(all_browse),
                domains=[
                    BrowseDomainCount(
                        domain=k,
                        label=domain_labels.get(k, k),
                        count=domain_counts.get(k, 0),
                    )
                    for k, _ in list_domains()
                    if domain_counts.get(k, 0) > 0
                ],
            )
        return DataTypeListResponse(items=items, domains=domains, summary=summary)

    async def browse_data(
        self,
        session,
        data_type: str,
        skip: int = 0,
        limit: int = 500,
        stock_code: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> DataBrowseResponse:
        entry = get_data_type_entry(data_type)
        if entry is None:
            raise NotFoundError(f"Unknown data_type: {data_type}")
        if not entry.is_activated or not entry.browse_enabled:
            raise ValidationError(f"Data type '{data_type}' is not available for browse")
        if not entry.table_name:
            raise ValidationError(f"Data type '{data_type}' has no table_name")

        filters: dict = {}
        if stock_code:
            filters["stock_code"] = stock_code
        if start_date:
            filters["start_date"] = start_date
        if end_date:
            filters["end_date"] = end_date

        limit = min(limit, 500)
        total = await self._query.count_rows(session, data_type, filters)
        items = await self._query.fetch_rows(session, data_type, skip, limit, filters)
        page = (skip // limit) + 1 if limit else 1

        return DataBrowseResponse(
            items=items,
            total=total,
            page=page,
            size=limit,
            data_type=data_type,
            label=entry.label,
            domain=entry.domain,
            table_name=entry.table_name,
            columns=entry.columns,
            filters=entry.filters,
        )

