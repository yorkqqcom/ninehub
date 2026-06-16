"""Apply daily-batch collect settings to the 31 workflow TIA overrides."""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.tia_override import TiaOverride
from app.services.tia.collect_pattern import enrich_schema_collect
from app.services.workflow.collect_batch import DAILY_BATCH_MODE_OVERRIDES, DAILY_MAX_API_CALLS, DAILY_MAX_CODES
from app.sync.tia_collect.params import SNAPSHOT_FULL_MARKET_PARAMS

WORKFLOW_APIS = list(DAILY_BATCH_MODE_OVERRIDES.keys())


async def apply(*, dry_run: bool = False) -> None:
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(select(TiaOverride).where(TiaOverride.api_name.in_(WORKFLOW_APIS)))
        ).scalars().all()
        by_api = {r.api_name: r for r in rows}
        updated = 0
        for api in WORKFLOW_APIS:
            row = by_api.get(api)
            if row is None:
                print(f"SKIP missing override: {api}")
                continue
            payload = dict(row.override_json or {})
            if api in SNAPSHOT_FULL_MARKET_PARAMS:
                schema = dict(payload.get("schema") or payload)
                schema["probe_params"] = dict(SNAPSHOT_FULL_MARKET_PARAMS[api])
            else:
                schema = dict(payload.get("schema") or payload)
                schema = enrich_schema_collect(schema, api)
            collect = dict(schema.get("collect") or {})
            collect["mode"] = DAILY_BATCH_MODE_OVERRIDES[api]
            collect["max_codes_per_run"] = DAILY_MAX_CODES
            collect["max_api_calls_per_run"] = DAILY_MAX_API_CALLS
            collect["batch_mode_default"] = "daily"
            schema["collect"] = collect
            if "schema" in payload:
                payload["schema"] = schema
            else:
                payload = schema
            row.override_json = payload
            updated += 1
            print(f"OK {api} mode={collect['mode']}")
        if dry_run:
            await session.rollback()
            print(f"Dry run: would update {updated} overrides")
        else:
            await session.commit()
            print(f"Updated {updated} overrides")


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    asyncio.run(apply(dry_run=dry_run))


if __name__ == "__main__":
    main()
