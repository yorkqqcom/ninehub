"""TIA L1 override CRUD and catalog merge."""

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.catalog.registry import entry_from_override, register_catalog_entry
from app.core.exceptions import NotFoundError, ValidationError
from app.models.tia_override import TiaOverride
from app.schemas.catalog import CatalogColumnMeta, CatalogFilterMeta
from app.services.tia.constants import (
    api_to_data_type,
    api_to_domain,
    api_to_label,
    api_to_table_name,
    data_type_aliases,
)
from app.services.tia.scan.tushare_doc_registry import resolve_api_meta


class TiaOverrideService:
    def build_override_from_api(
        self,
        api_name: str,
        domain: str | None = None,
        min_points: int | None = None,
    ) -> TiaOverride:
        from app.catalog.tia_probe_registry import OFFICIAL_ONLY_API_PROBES

        meta = OFFICIAL_ONLY_API_PROBES.get(api_name) or resolve_api_meta(api_name) or {}
        data_type = api_to_data_type(api_name)
        doc_id = meta.get("doc_id")
        doc_url = meta.get("doc_url") or (
            f"https://tushare.pro/document/2?doc_id={doc_id}" if doc_id else None
        )
        if min_points is not None:
            min_points_val = int(min_points)
        else:
            min_points_val = meta.get("min_points")
            if min_points_val is None:
                from app.services.tushare.quota import api_min_points

                min_points_val = api_min_points(api_name)
        return TiaOverride(
            api_name=api_name,
            data_type=data_type,
            domain=domain or api_to_domain(api_name),
            label=meta.get("label") or api_to_label(api_name),
            min_points=int(min_points_val),
            doc_url=doc_url,
            table_name=api_to_table_name(api_name),
            is_activated=False,
            override_json={"source": "tia_l1", "api_name": api_name},
        )

    async def create_from_api(
        self,
        session: AsyncSession,
        api_name: str,
        domain: str | None = None,
        min_points: int | None = None,
    ) -> TiaOverride:
        existing = await session.execute(
            select(TiaOverride).where(TiaOverride.api_name == api_name)
        )
        if existing.scalar_one_or_none():
            raise ValidationError(f"Override already exists for api {api_name}")
        override = self.build_override_from_api(api_name, domain=domain, min_points=min_points)
        session.add(override)
        await session.flush()
        await session.refresh(override)
        return override

    def apply_to_registry(
        self,
        override: TiaOverride,
        columns: List[CatalogColumnMeta] | None = None,
        filters: List[CatalogFilterMeta] | None = None,
        browse_enabled: bool | None = None,
    ) -> None:
        table_name = override.table_name
        oj = override.override_json or {}
        enabled = browse_enabled if browse_enabled is not None else bool(oj.get("browse_enabled"))
        if columns is None or filters is None:
            schema = oj.get("schema") or {}
            if schema:
                from app.services.tia.schema_inference import (
                    schema_to_catalog_columns,
                    schema_to_catalog_filters,
                )

                if columns is None:
                    columns = schema_to_catalog_columns(schema)
                if filters is None:
                    filters = schema_to_catalog_filters(schema)
        entry = entry_from_override(
            api_name=override.api_name,
            data_type=override.data_type,
            domain=override.domain,
            label=override.label,
            min_points=override.min_points,
            table_name=table_name,
            is_activated=override.is_activated,
            doc_url=override.doc_url,
            columns=columns,
            filters=filters,
            browse_enabled=enabled,
        )
        register_catalog_entry(entry)
        for alias in data_type_aliases(override.api_name):
            if alias == override.data_type:
                continue
            # Legacy aliases (e.g. tia_trade_cal) are sync/lookup keys only — not browse entries.
            register_catalog_entry(
                entry_from_override(
                    api_name=override.api_name,
                    data_type=alias,
                    domain=override.domain,
                    label=override.label,
                    min_points=override.min_points,
                    table_name=table_name,
                    is_activated=override.is_activated,
                    doc_url=override.doc_url,
                    columns=columns,
                    filters=filters,
                    browse_enabled=False,
                )
            )

    async def list_all(self, session: AsyncSession) -> list[TiaOverride]:
        result = await session.execute(select(TiaOverride))
        return list(result.scalars().all())

    def list_all_sync(self, session: Session) -> list[TiaOverride]:
        return list(session.execute(select(TiaOverride)).scalars().all())

    async def get_by_api(self, session: AsyncSession, api_name: str) -> TiaOverride:
        result = await session.execute(
            select(TiaOverride).where(TiaOverride.api_name == api_name)
        )
        override = result.scalar_one_or_none()
        if override is None:
            raise NotFoundError(f"TIA override not found for {api_name}")
        return override

    def get_by_api_sync(self, session: Session, api_name: str) -> TiaOverride:
        override = session.execute(
            select(TiaOverride).where(TiaOverride.api_name == api_name)
        ).scalar_one_or_none()
        if override is None:
            raise NotFoundError(f"TIA override not found for {api_name}")
        return override

    async def load_all_into_registry(self, session: AsyncSession) -> int:
        overrides = await self.list_all(session)
        for override in overrides:
            self.bootstrap_override(override)
        return len(overrides)

    def bootstrap_override(self, override: TiaOverride) -> None:
        """Restore catalog entry and handler for one override."""
        self.apply_to_registry(override)
        if override.is_activated:
            oj = override.override_json or {}
            schema = oj.get("schema") or {}
            from app.sync.tia_handler import register_tia_handler

            register_tia_handler(override.api_name, override.data_type, schema)

    def load_all_into_registry_sync(self, session: Session) -> int:
        overrides = self.list_all_sync(session)
        for override in overrides:
            self.bootstrap_override(override)
        return len(overrides)

    async def enable_browse(self, session: AsyncSession, api_name: str) -> TiaOverride:
        override = await self.get_by_api(session, api_name)
        if not override.is_activated:
            raise ValidationError(f"Override for {api_name} is not activated")
        oj = dict(override.override_json or {})
        if oj.get("browse_enabled"):
            return override
        oj["browse_enabled"] = True
        override.override_json = oj
        schema = oj.get("schema") or {}
        from app.services.tia.schema_inference import (
            schema_to_catalog_columns,
            schema_to_catalog_filters,
        )

        self.apply_to_registry(
            override,
            columns=schema_to_catalog_columns(schema) if schema else None,
            filters=schema_to_catalog_filters(schema) if schema else None,
            browse_enabled=True,
        )
        await session.flush()
        await session.refresh(override)
        return override
