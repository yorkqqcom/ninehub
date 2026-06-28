"""Apply daily-batch collect settings to TDX L3 overrides (file_import / concept snapshot)."""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal
from app.services.tia.collect_pattern import enrich_schema_collect
from app.services.tia.override_service import TiaOverrideService
from app.services.workflow.collect_batch import (
    DAILY_MAX_API_CALLS,
    resolve_daily_max_codes,
)

TDX_WORKFLOW_APIS = ("bar_1d", "bar_1m", "bar_5m", "concept_index", "concept_member")

TDX_COLLECT_MODES = {
    "bar_1d": "file_import",
    "bar_1m": "file_import",
    "bar_5m": "file_import",
    "concept_index": "tdx_concept_snapshot",
    "concept_member": "tdx_concept_snapshot",
}


async def sync_tdx_override_data_types(*, dry_run: bool = False) -> int:
    """Align tia_overrides.data_type with applied TDX proposals (tdx_*)."""
    updated = 0
    async with AsyncSessionLocal() as session:
        proposals = (
            await session.execute(
                select(TiaProposal).where(
                    TiaProposal.status == "applied",
                    TiaProposal.data_type.like("tdx_%"),
                    TiaProposal.api_name.in_(TDX_WORKFLOW_APIS),
                )
            )
        ).scalars().all()
        by_api = {
            r.api_name: r
            for r in (
                await session.execute(
                    select(TiaOverride).where(TiaOverride.api_name.in_(TDX_WORKFLOW_APIS))
                )
            ).scalars().all()
        }
        for proposal in proposals:
            override = by_api.get(proposal.api_name)
            if override is None:
                continue
            canonical = proposal.data_type
            if override.data_type == canonical:
                continue
            print(
                f"REPAIR {proposal.api_name}: "
                f"{override.data_type} -> {canonical} (table={override.table_name})"
            )
            override.data_type = canonical
            updated += 1
        if dry_run:
            await session.rollback()
            print(f"Dry run: would repair {updated} override data_type(s)")
            return updated
        await session.commit()
        print(f"Repaired {updated} override data_type(s)")
    if updated and not dry_run:
        reload_catalog_from_db()
    return updated


def reload_catalog_from_db() -> None:
    from sqlalchemy.orm import Session

    from app.core.database import sync_engine

    with Session(sync_engine) as sync_sess:
        TiaOverrideService().load_all_into_registry_sync(sync_sess)


async def apply(*, dry_run: bool = False) -> None:
    await sync_tdx_override_data_types(dry_run=dry_run)
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(TiaOverride).where(TiaOverride.api_name.in_(TDX_WORKFLOW_APIS))
            )
        ).scalars().all()
        by_api = {r.api_name: r for r in rows}
        updated = 0
        for api in TDX_WORKFLOW_APIS:
            row = by_api.get(api)
            if row is None:
                print(f"SKIP missing override: {api} (run TDX L3 activation first)")
                continue
            mode = TDX_COLLECT_MODES[api]
            payload = dict(row.override_json or {})
            schema = dict(payload.get("schema") or payload)
            schema = enrich_schema_collect(schema, api)
            collect = dict(schema.get("collect") or {})
            collect["mode"] = mode
            collect["max_codes_per_run"] = resolve_daily_max_codes(api, mode)
            collect["max_api_calls_per_run"] = min(
                int(collect.get("max_api_calls_per_run") or DAILY_MAX_API_CALLS),
                500 if mode == "file_import" else DAILY_MAX_API_CALLS,
            )
            collect["batch_mode_default"] = "daily"
            schema["collect"] = collect
            if "schema" in payload:
                payload["schema"] = schema
            else:
                payload = schema
            row.override_json = payload
            updated += 1
            print(f"OK {api} mode={mode} max_codes={collect['max_codes_per_run']}")
        if dry_run:
            await session.rollback()
            print(f"Dry run: would update {updated} TDX overrides")
        else:
            await session.commit()
            print(f"Updated {updated} TDX overrides")
            reload_catalog_from_db()


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    asyncio.run(apply(dry_run=dry_run))


if __name__ == "__main__":
    main()
