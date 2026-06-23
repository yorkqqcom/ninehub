#!/usr/bin/env python3
"""Patch stock_basic L3 schema (add name) and re-collect full snapshot."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from browser_bootstrap_lib import db_session

from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal  # noqa: F401
from app.models.user import User  # noqa: F401
from app.services.tia.credentials import require_tushare_token, resolve_tushare_collect_credentials
from app.services.tia.override_service import TiaOverrideService
from app.services.tushare.source_quota import resolve_max_calls_per_minute
from app.sync.executor import SyncExecutor
from app.sync.handlers import SyncContext

DATA_TYPE = "tushare_stock_basic"
API_NAME = "stock_basic"


def patch_schema(schema: dict) -> dict:
    """Ensure Tushare ``name`` and other stock_basic fields are in L3 schema."""
    schema = dict(schema)
    columns = [dict(c) for c in (schema.get("columns") or [])]
    keys = {c.get("key") for c in columns}
    if "name" not in keys:
        insert_at = next((i + 1 for i, c in enumerate(columns) if c.get("key") == "stock_code"), 0)
        columns.insert(
            insert_at,
            {
                "key": "name",
                "label": "名称",
                "type": "string",
                "nullable": True,
                "api_field": "name",
            },
        )
    mappings = dict(schema.get("field_mappings") or {})
    mappings.setdefault("name", "name")
    api_fields = list(schema.get("api_fields") or [])
    if "name" not in api_fields:
        if "ts_code" in api_fields:
            api_fields.insert(api_fields.index("ts_code") + 1, "name")
        else:
            api_fields.insert(0, "name")
    schema["columns"] = columns
    schema["field_mappings"] = mappings
    schema["api_fields"] = api_fields
    return schema


def _resolve_source(session: Session) -> tuple[str, str, dict, int | None]:
    creds = resolve_tushare_collect_credentials(session)
    return (
        str(creds.get("provider") or "tushare"),
        str(creds.get("token") or ""),
        dict(creds.get("source_config") or {}),
        creds.get("source_id"),
    )


def resync(*, patch_only: bool = False) -> int:
    session = db_session()
    override = session.execute(
        select(TiaOverride).where(TiaOverride.data_type == DATA_TYPE).limit(1)
    ).scalar_one_or_none()
    if override is None or not override.is_activated:
        print(f"{DATA_TYPE} 未 L3 激活")
        return 1

    oj = dict(override.override_json or {})
    patched = patch_schema(dict(oj.get("schema") or {}))
    if patched != oj.get("schema"):
        oj["schema"] = patched
        override.override_json = oj
        session.commit()
        print("已补全 L3 schema（含 name 字段）")
    else:
        print("L3 schema 已含 name，跳过 patch")

    TiaOverrideService().load_all_into_registry_sync(session)

    if patch_only:
        return 0

    provider, token, source_config, source_id = _resolve_source(session)
    require_tushare_token({"token": token})

    table_name = override.table_name or DATA_TYPE
    before = session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
    print(f"重采 {API_NAME} snapshot（表内 {before} 行）…")

    today = date.today()
    result = SyncExecutor().run(
        SyncContext(
            data_type=DATA_TYPE,
            source_id=source_id or 1,
            start_date=today,
            end_date=today,
            extra={
                "session": session,
                "provider": provider,
                "token": token,
                "source_config": source_config,
                "max_calls_per_minute": resolve_max_calls_per_minute(source_config),
                "table_name": table_name,
                "workflow_schema": patched,
            },
        )
    )
    session.commit()

    after = session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
    sample = session.execute(
        text(
            "SELECT COUNT(*) FILTER (WHERE name IS NOT NULL), "
            "COUNT(*) FILTER (WHERE exchange IS NOT NULL), "
            "COUNT(*) FILTER (WHERE delist_date IS NOT NULL) "
            f'FROM "{table_name}"'
        )
    ).one()
    print(result.message)
    print(f"行数 {before} → {after}；name={sample[0]} exchange={sample[1]} delist_date={sample[2]}")
    return 0 if result.rows_upserted else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch & resync tushare_stock_basic")
    parser.add_argument("--patch-only", action="store_true", help="仅补 schema，不调用 Tushare")
    args = parser.parse_args()
    raise SystemExit(resync(patch_only=args.patch_only))


if __name__ == "__main__":
    main()
