"""Data standard checklist — one row per TIA proposal (latest per api_name)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal
from app.schemas.catalog import (
    DataStandardDetailResponse,
    DataStandardFieldItem,
    DataStandardIndexItem,
    DataStandardListResponse,
    DataStandardSummary,
    DataStandardSummaryItem,
    DriftDetailResponse,
    NamingComplianceItem,
    QualitySuggestionItem,
    QualitySuggestionsResponse,
    DataStandardExportResponse,
)
from app.services.catalog.canonical_standard import (
    build_checklist_from_schema,
    resolve_api_fields,
    resolve_probe_status,
    resolve_schema_for_ddl,
    validate_canonical_for_ddl,
)
from app.services.catalog.drift_service import build_drift_report, compute_doc_drift, compute_live_drift
from app.services.catalog.schema_export import (
    SUPPORTED_BUNDLE_FORMATS,
    SUPPORTED_EXPORT_FORMATS,
    build_export_zip,
    build_json_schema,
    build_openapi_document,
)
from app.services.catalog.naming_compliance import (
    audit_naming_compliance,
    resolve_provider_id,
    resolve_table_name,
)
from app.services.tia.proposal_enrichment import build_api_meta_map, enrich_proposal
from app.services.tia.collect_pattern import resolve_collect_pattern
from app.services.tia.scan.tushare_doc_registry import infer_probe_category, load_api_by_doc_id
from app.services.tia.constants import api_to_data_type, api_to_domain, api_to_label

_CATEGORY_TO_DOMAIN: dict[str, str] = {
    "股票数据": "basic",
    "指数专题": "index",
    "宏观经济": "macro",
    "行业经济": "macro",
}


def _last_probe_at(proposal: TiaProposal) -> str | None:
    steps = proposal.activation_steps or {}
    if steps.get("preflight_test", {}).get("actual_fields"):
        updated = getattr(proposal, "updated_at", None)
        if updated is not None:
            return updated.isoformat()
    return None


def _resolve_drift_status_light(
    api_name: str,
    schema: dict | None,
    proposal: TiaProposal,
    is_activated: bool,
) -> str:
    if not schema:
        return "none"
    api_fields = list(schema.get("api_fields") or [])
    doc = compute_doc_drift(api_name, api_fields)
    live = compute_live_drift(api_fields, proposal.activation_steps)
    if live.get("has_drift"):
        return "live_drift"
    if doc.get("has_drift"):
        return "doc_drift"
    if is_activated:
        return "none"
    return "none"


def _enrich_item_meta(
    *,
    api_name: str,
    data_type: str,
    override: TiaOverride | None,
    schema: dict | None,
) -> dict:
    provider_id = resolve_provider_id(data_type, api_name)
    if override and override.data_type:
        provider_id = resolve_provider_id(override.data_type, api_name)
    table_name = resolve_table_name(
        api_name,
        data_type,
        override_table_name=override.table_name if override else None,
        provider_id=provider_id,
    )
    compliance_raw = audit_naming_compliance(
        api_name=api_name,
        data_type=data_type,
        table_name=table_name,
        provider_id=provider_id,
        schema=schema,
    )
    return {
        "provider_id": provider_id,
        "table_name": table_name,
        "naming_compliance": NamingComplianceItem(**compliance_raw),
    }


def _build_quality_suggestions(data_type: str, schema: dict) -> list[QualitySuggestionItem]:
    unique_keys = set(schema.get("unique_keys") or [])
    suggestions: list[QualitySuggestionItem] = []
    seen: set[str] = set()
    for col in schema.get("columns") or []:
        key = col.get("key")
        if not key or key in seen:
            continue
        in_unique = key in unique_keys
        non_nullable = not col.get("nullable", True)
        if not in_unique and not non_nullable:
            continue
        seen.add(key)
        suggestions.append(
            QualitySuggestionItem(
                rule_type="no_nulls",
                target_data_type=data_type,
                column=key,
                reason="unique_key" if in_unique else "non_nullable",
                config_json={"fields": [key]},
            )
        )
    return suggestions


def _field_source(probe_status: str) -> str:
    if probe_status == "configured":
        return "catalog_probe"
    if probe_status == "template":
        return "template"
    return "none"


def _schema_stage(
    *,
    probe_status: str,
    override: TiaOverride | None,
    ddl_ready: bool,
    is_activated: bool,
) -> str:
    if is_activated:
        return "activated"
    if ddl_ready:
        return "schema_ready"
    if probe_status == "unconfigured":
        return "await_probe"
    oj = (override.override_json or {}) if override else {}
    if oj.get("schema", {}).get("columns"):
        return "schema_persisted"
    return "schema_preview"


def _domain_for_proposal(
    proposal: TiaProposal,
    meta: dict,
    override: TiaOverride | None,
) -> str:
    if override and override.domain:
        return override.domain
    if proposal.data_type:
        from app.catalog.registry import get_data_type_entry

        entry = get_data_type_entry(proposal.data_type)
        if entry:
            return entry.domain
    category = meta.get("category")
    if category and category in _CATEGORY_TO_DOMAIN:
        return _CATEGORY_TO_DOMAIN[category]
    return api_to_domain(proposal.api_name)


def _meta_for_proposal(proposal: TiaProposal, api_meta: dict[str, dict]) -> dict:
    meta = {**api_meta.get(proposal.api_name, {}), **enrich_proposal(proposal, api_meta)}
    if not meta.get("probe_category"):
        for row in load_api_by_doc_id().values():
            if row.get("api") == proposal.api_name:
                meta["probe_category"] = infer_probe_category(
                    category=row.get("category"),
                    subcategory=row.get("subcategory"),
                    explicit=row.get("probe_category"),
                )
                meta.setdefault("category", row.get("category"))
                break
    return meta


async def _latest_proposals_by_api(session: AsyncSession) -> list[TiaProposal]:
    rows = (
        await session.execute(select(TiaProposal).order_by(TiaProposal.id.desc()))
    ).scalars().all()
    seen: set[str] = set()
    latest: list[TiaProposal] = []
    for proposal in rows:
        if proposal.api_name in seen:
            continue
        seen.add(proposal.api_name)
        latest.append(proposal)
    return latest


def _proposal_for_api(session_proposals: list[TiaProposal], api_name: str) -> TiaProposal | None:
    for proposal in session_proposals:
        if proposal.api_name == api_name:
            return proposal
    return None


def _placeholder_summary(
    proposal: TiaProposal,
    meta: dict,
    override: TiaOverride | None,
) -> DataStandardSummaryItem:
    probe_category = meta.get("probe_category")
    probe_status = resolve_probe_status(proposal.api_name, probe_category)
    pattern = resolve_collect_pattern(proposal.api_name)
    is_activated = bool(override and override.is_activated)
    data_type = proposal.data_type or api_to_data_type(proposal.api_name)
    meta_extra = _enrich_item_meta(
        api_name=proposal.api_name,
        data_type=data_type,
        override=override,
        schema=None,
    )
    return DataStandardSummaryItem(
        api_name=proposal.api_name,
        data_type=data_type,
        label=meta.get("label") or api_to_label(proposal.api_name),
        domain=_domain_for_proposal(proposal, meta, override),
        doc_id=meta.get("doc_id"),
        doc_url=meta.get("doc_url"),
        is_activated=is_activated,
        proposal_id=proposal.id,
        proposal_status=proposal.status,
        proposal_reason=proposal.reason,
        probe_status=probe_status,
        probe_category=probe_category,
        category=meta.get("category"),
        field_source=_field_source(probe_status),
        schema_stage=_schema_stage(
            probe_status=probe_status,
            override=override,
            ddl_ready=False,
            is_activated=is_activated,
        ),
        drift_status="none",
        last_probe_at=_last_probe_at(proposal),
        unique_keys=[],
        api_field_count=0,
        standard_field_count=0,
        matched_count=0,
        missing_count=0,
        extra_count=0,
        type_mismatch_count=0,
        coverage_pct=0.0,
        ddl_ready=False,
        ddl_errors=["无探针字段；请在 TIA 工作台运行扫描 probe"],
        collect_pattern=pattern.pattern_key,
        collect_mode=pattern.mode,
        pattern_mismatch=pattern.pattern_mismatch,
        pattern_warnings=list(pattern.warnings),
        **meta_extra,
    )


def _summary_from_schema(
    proposal: TiaProposal,
    schema: dict,
    *,
    meta: dict,
    override: TiaOverride | None,
    include_fields: bool = False,
) -> DataStandardSummaryItem | DataStandardDetailResponse:
    fields_raw, extra_raw, counts = build_checklist_from_schema(schema)
    api_name = proposal.api_name
    data_type = proposal.data_type or (override.data_type if override else api_to_data_type(api_name))
    from app.catalog.registry import get_data_type_entry

    entry = get_data_type_entry(data_type)
    label = meta.get("label") or api_to_label(api_name)
    domain = _domain_for_proposal(proposal, meta, override)
    is_activated = override.is_activated if override else bool(entry and entry.is_activated)
    ddl_errors = validate_canonical_for_ddl(schema, api_name)
    probe_category = meta.get("probe_category")
    probe_status = resolve_probe_status(api_name, probe_category)
    cp = schema.get("collect_pattern") or {}
    pattern = resolve_collect_pattern(api_name)
    collect_pattern = cp.get("pattern") or pattern.pattern_key
    collect_mode = cp.get("mode") or pattern.mode
    pattern_mismatch = bool(cp.get("pattern_mismatch", pattern.pattern_mismatch))
    pattern_warnings = list(cp.get("warnings") or pattern.warnings)
    meta_extra = _enrich_item_meta(
        api_name=api_name,
        data_type=data_type,
        override=override,
        schema=schema,
    )

    item_data = dict(
        api_name=api_name,
        data_type=data_type,
        label=label,
        domain=domain,
        doc_id=meta.get("doc_id"),
        doc_url=meta.get("doc_url"),
        is_activated=is_activated,
        proposal_id=proposal.id,
        proposal_status=proposal.status,
        proposal_reason=proposal.reason,
        probe_status=probe_status,
        probe_category=probe_category,
        category=meta.get("category"),
        field_source=_field_source(probe_status),
        schema_stage=_schema_stage(
            probe_status=probe_status,
            override=override,
            ddl_ready=len(ddl_errors) == 0,
            is_activated=is_activated,
        ),
        drift_status=_resolve_drift_status_light(
            api_name, schema, proposal, is_activated
        ),
        last_probe_at=_last_probe_at(proposal),
        unique_keys=list(schema.get("unique_keys") or []),
        indexes=[
            DataStandardIndexItem(**idx) for idx in (schema.get("indexes") or [])
        ],
        unique_constraint=schema.get("unique_constraint"),
        ddl_ready=len(ddl_errors) == 0,
        ddl_errors=ddl_errors,
        collect_pattern=collect_pattern,
        collect_mode=collect_mode,
        pattern_mismatch=pattern_mismatch,
        pattern_warnings=pattern_warnings,
        **meta_extra,
        **counts,
    )
    if include_fields:
        return DataStandardDetailResponse(
            fields=[DataStandardFieldItem(**f) for f in fields_raw],
            extra_fields=[DataStandardFieldItem(**f) for f in extra_raw],
            field_mappings=schema.get("field_mappings") or {},
            **item_data,
        )
    return DataStandardSummaryItem(**item_data)


def _proposal_for_data_type(proposals: list[TiaProposal], data_type: str) -> TiaProposal | None:
    for proposal in proposals:
        dt = proposal.data_type or api_to_data_type(proposal.api_name)
        if dt == data_type:
            return proposal
    return None


async def _load_standard_context(
    session: AsyncSession,
    api_name: str,
) -> tuple[TiaProposal, TiaOverride | None, dict, dict]:
    proposals = await _latest_proposals_by_api(session)
    proposal = _proposal_for_api(proposals, api_name)
    if proposal is None:
        raise NotFoundError(f"No TIA proposal for api '{api_name}'")
    if not resolve_api_fields(api_name):
        raise NotFoundError(
            f"No probe fields for api '{api_name}'; run TIA scan probe first"
        )
    override_rows = await session.execute(
        select(TiaOverride).where(TiaOverride.api_name == api_name)
    )
    override = override_rows.scalar_one_or_none()
    api_meta = build_api_meta_map()
    meta = _meta_for_proposal(proposal, api_meta)
    existing = (override.override_json or {}).get("schema") if override else None
    schema = resolve_schema_for_ddl(api_name, existing)
    return proposal, override, meta, schema


def _build_export_entry(
    *,
    api_name: str,
    proposal: TiaProposal,
    override: TiaOverride | None,
    meta: dict,
    schema: dict,
) -> dict[str, Any]:
    data_type = proposal.data_type or (
        override.data_type if override else api_to_data_type(api_name)
    )
    provider_id = resolve_provider_id(data_type, api_name)
    table_name = resolve_table_name(
        api_name,
        data_type,
        override_table_name=override.table_name if override else None,
        provider_id=provider_id,
    )
    label = meta.get("label") or api_to_label(api_name)
    json_schema = build_json_schema(
        api_name=api_name,
        data_type=data_type,
        label=label,
        table_name=table_name,
        provider_id=provider_id,
        schema=schema,
    )
    return {
        "api_name": api_name,
        "data_type": data_type,
        "label": label,
        "json_schema": json_schema,
        "file": f"schemas/{api_name}.schema.json",
    }


class DataStandardService:
    def build_schema_for_api(
        self,
        api_name: str,
        override: TiaOverride | None = None,
        *,
        actual_fields: list[str] | None = None,
        force_rebuild: bool = False,
    ) -> dict:
        existing = (override.override_json or {}).get("schema") if override else None
        return resolve_schema_for_ddl(
            api_name,
            existing,
            actual_fields=actual_fields,
            force_rebuild=force_rebuild,
        )

    async def list_standards(
        self,
        session: AsyncSession,
        *,
        domain: str | None = None,
        api: str | None = None,
        provider_id: str | None = None,
        drift_status: str | None = None,
        q: str | None = None,
        min_coverage: float | None = None,
        ddl_ready: bool | None = None,
        probe_status: str | None = None,
        proposal_status: str | None = None,
        skip: int = 0,
        limit: int = 100,
    ) -> DataStandardListResponse:
        override_rows = await session.execute(select(TiaOverride))
        override_by_api = {row.api_name: row for row in override_rows.scalars().all()}
        proposals = await _latest_proposals_by_api(session)
        api_meta = build_api_meta_map()

        items: list[DataStandardSummaryItem] = []
        for proposal in proposals:
            api_name = proposal.api_name
            meta = _meta_for_proposal(proposal, api_meta)
            override = override_by_api.get(api_name)

            if not resolve_api_fields(api_name):
                item = _placeholder_summary(proposal, meta, override)
            else:
                schema = self.build_schema_for_api(api_name, override)
                built = _summary_from_schema(
                    proposal, schema, meta=meta, override=override, include_fields=False
                )
                assert isinstance(built, DataStandardSummaryItem)
                item = built

            if domain and item.domain != domain:
                continue
            if api and item.api_name != api:
                continue
            if provider_id and item.provider_id != provider_id:
                continue
            if drift_status and item.drift_status != drift_status:
                continue
            if min_coverage is not None and item.coverage_pct < min_coverage:
                continue
            if ddl_ready is not None and item.ddl_ready != ddl_ready:
                continue
            if probe_status and item.probe_status != probe_status:
                continue
            if proposal_status and item.proposal_status != proposal_status:
                continue
            if q:
                needle = q.strip().lower()
                haystack = " ".join(
                    filter(
                        None,
                        [
                            api_name.lower(),
                            item.label.lower(),
                            item.data_type.lower(),
                            (item.category or "").lower(),
                            (item.proposal_reason or "").lower(),
                        ],
                    )
                )
                if needle not in haystack:
                    continue
            items.append(item)

        total = len(items)
        full_match = sum(
            1
            for i in items
            if i.missing_count == 0 and i.extra_count == 0 and i.type_mismatch_count == 0 and i.api_field_count
        )
        summary = DataStandardSummary(
            total=total,
            full_match_count=full_match,
            partial_match_count=sum(1 for i in items if 0 < i.coverage_pct < 100),
            gap_count=sum(1 for i in items if i.missing_count > 0),
            ddl_ready_count=sum(1 for i in items if i.ddl_ready),
            activated_count=sum(1 for i in items if i.is_activated),
            schema_ready_count=sum(1 for i in items if i.schema_stage == "schema_ready"),
            proposal_total=len(proposals),
            pending_count=sum(1 for i in items if i.proposal_status == "pending"),
            applied_count=sum(1 for i in items if i.proposal_status == "applied"),
            configured_count=sum(1 for i in items if i.probe_status == "configured"),
            template_count=sum(1 for i in items if i.probe_status == "template"),
            unconfigured_count=sum(1 for i in items if i.probe_status == "unconfigured"),
            drift_count=sum(1 for i in items if i.drift_status != "none"),
        )

        limit = min(max(limit, 1), 500)
        page_items = items[skip : skip + limit]
        page = (skip // limit) + 1 if limit else 1

        return DataStandardListResponse(
            items=page_items,
            total=total,
            page=page,
            size=limit,
            summary=summary,
        )

    async def get_standard_detail(
        self,
        session: AsyncSession,
        api_name: str,
    ) -> DataStandardDetailResponse:
        proposals = await _latest_proposals_by_api(session)
        proposal = _proposal_for_api(proposals, api_name)
        if proposal is None:
            raise NotFoundError(f"No TIA proposal for api '{api_name}'")
        if not resolve_api_fields(api_name):
            raise NotFoundError(
                f"No probe fields for api '{api_name}'; run TIA scan probe first"
            )
        api_meta = build_api_meta_map()
        meta = _meta_for_proposal(proposal, api_meta)
        override_rows = await session.execute(
            select(TiaOverride).where(TiaOverride.api_name == api_name)
        )
        override = override_rows.scalar_one_or_none()
        schema = self.build_schema_for_api(api_name, override)
        item = _summary_from_schema(
            proposal, schema, meta=meta, override=override, include_fields=True
        )
        assert isinstance(item, DataStandardDetailResponse)
        return item

    async def get_drift_detail(
        self,
        session: AsyncSession,
        api_name: str,
    ) -> DriftDetailResponse:
        proposals = await _latest_proposals_by_api(session)
        proposal = _proposal_for_api(proposals, api_name)
        if proposal is None:
            raise NotFoundError(f"No TIA proposal for api '{api_name}'")
        override_rows = await session.execute(
            select(TiaOverride).where(TiaOverride.api_name == api_name)
        )
        override = override_rows.scalar_one_or_none()
        if not resolve_api_fields(api_name):
            raise NotFoundError(
                f"No probe fields for api '{api_name}'; run TIA scan probe first"
            )
        schema = self.build_schema_for_api(api_name, override)
        data_type = proposal.data_type or (
            override.data_type if override else api_to_data_type(api_name)
        )
        is_activated = bool(override and override.is_activated)
        provider = resolve_provider_id(data_type, api_name)
        report = await build_drift_report(
            session,
            api_name=api_name,
            data_type=data_type,
            schema=schema,
            activation_steps=proposal.activation_steps,
            is_activated=is_activated,
            override_table_name=override.table_name if override else None,
            provider_id=provider,
            last_probe_at=_last_probe_at(proposal),
        )
        return DriftDetailResponse(api_name=api_name, data_type=data_type, **report)

    async def get_quality_suggestions(
        self,
        session: AsyncSession,
        api_name: str,
    ) -> QualitySuggestionsResponse:
        proposals = await _latest_proposals_by_api(session)
        proposal = _proposal_for_api(proposals, api_name)
        if proposal is None:
            raise NotFoundError(f"No TIA proposal for api '{api_name}'")
        override_rows = await session.execute(
            select(TiaOverride).where(TiaOverride.api_name == api_name)
        )
        override = override_rows.scalar_one_or_none()
        if not resolve_api_fields(api_name):
            raise NotFoundError(
                f"No probe fields for api '{api_name}'; run TIA scan probe first"
            )
        schema = self.build_schema_for_api(api_name, override)
        data_type = proposal.data_type or (
            override.data_type if override else api_to_data_type(api_name)
        )
        suggestions = _build_quality_suggestions(data_type, schema)
        return QualitySuggestionsResponse(
            api_name=api_name,
            data_type=data_type,
            suggestions=suggestions,
        )

    async def get_quality_suggestions_by_data_type(
        self,
        session: AsyncSession,
        data_type: str,
    ) -> QualitySuggestionsResponse:
        proposals = await _latest_proposals_by_api(session)
        proposal = _proposal_for_data_type(proposals, data_type)
        if proposal is None:
            raise NotFoundError(f"No TIA proposal for data_type '{data_type}'")
        return await self.get_quality_suggestions(session, proposal.api_name)

    async def export_schema(
        self,
        session: AsyncSession,
        api_name: str,
        *,
        export_format: str = "json_schema",
    ) -> DataStandardExportResponse:
        if export_format not in SUPPORTED_EXPORT_FORMATS:
            raise ValidationError(
                f"Unsupported export format: {export_format}; "
                f"use one of {sorted(SUPPORTED_EXPORT_FORMATS)}"
            )
        proposal, override, meta, schema = await _load_standard_context(session, api_name)
        entry = _build_export_entry(
            api_name=api_name,
            proposal=proposal,
            override=override,
            meta=meta,
            schema=schema,
        )
        if export_format == "openapi":
            openapi_doc = build_openapi_document([entry], title=f"NineHub — {entry['label']}")
            return DataStandardExportResponse(
                api_name=entry["api_name"],
                data_type=entry["data_type"],
                label=entry["label"],
                format=export_format,
                openapi=openapi_doc,
            )
        return DataStandardExportResponse(
            api_name=entry["api_name"],
            data_type=entry["data_type"],
            label=entry["label"],
            format=export_format,
            json_schema=entry["json_schema"],
        )

    async def export_schema_by_data_type(
        self,
        session: AsyncSession,
        data_type: str,
        *,
        export_format: str = "json_schema",
    ) -> DataStandardExportResponse:
        proposals = await _latest_proposals_by_api(session)
        proposal = _proposal_for_data_type(proposals, data_type)
        if proposal is None:
            raise NotFoundError(f"No TIA proposal for data_type '{data_type}'")
        return await self.export_schema(
            session, proposal.api_name, export_format=export_format
        )

    async def collect_export_entries(
        self,
        session: AsyncSession,
        *,
        domain: str | None = None,
        provider_id: str | None = None,
        ddl_ready: bool | None = None,
    ) -> list[dict[str, Any]]:
        override_rows = await session.execute(select(TiaOverride))
        override_by_api = {row.api_name: row for row in override_rows.scalars().all()}
        proposals = await _latest_proposals_by_api(session)
        api_meta = build_api_meta_map()
        entries: list[dict[str, Any]] = []

        for proposal in proposals:
            api_name = proposal.api_name
            if not resolve_api_fields(api_name):
                continue
            meta = _meta_for_proposal(proposal, api_meta)
            override = override_by_api.get(api_name)
            existing = (override.override_json or {}).get("schema") if override else None
            schema = resolve_schema_for_ddl(api_name, existing)
            data_type = proposal.data_type or (
                override.data_type if override else api_to_data_type(api_name)
            )
            if domain:
                domain_val = _domain_for_proposal(proposal, meta, override)
                if domain_val != domain:
                    continue
            if provider_id:
                pid = resolve_provider_id(data_type, api_name)
                if pid != provider_id:
                    continue
            if ddl_ready is not None:
                ddl_errors = validate_canonical_for_ddl(schema, api_name)
                ready = len(ddl_errors) == 0
                if ready != ddl_ready:
                    continue
            entries.append(
                _build_export_entry(
                    api_name=api_name,
                    proposal=proposal,
                    override=override,
                    meta=meta,
                    schema=schema,
                )
            )
        return entries

    async def export_bundle(
        self,
        session: AsyncSession,
        *,
        bundle_format: str = "zip_json_schema",
        domain: str | None = None,
        provider_id: str | None = None,
        ddl_ready: bool | None = None,
    ) -> tuple[bytes, str]:
        if bundle_format not in SUPPORTED_BUNDLE_FORMATS:
            raise ValidationError(
                f"Unsupported bundle format: {bundle_format}; "
                f"use one of {sorted(SUPPORTED_BUNDLE_FORMATS)}"
            )
        entries = await self.collect_export_entries(
            session,
            domain=domain,
            provider_id=provider_id,
            ddl_ready=ddl_ready,
        )
        if not entries:
            raise NotFoundError("No exportable schemas match filters")

        if bundle_format == "openapi":
            doc = build_openapi_document(entries)
            content = json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8")
            return content, "ninehub_catalog_openapi.json"

        zip_format = bundle_format
        content = build_export_zip(entries, bundle_format=zip_format)
        return content, f"ninehub_catalog_{zip_format}.zip"
