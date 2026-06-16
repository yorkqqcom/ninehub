"""Schema drift detection — doc / live probe / physical DDL."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.catalog.field_resolution import (
    live_fields_from_activation_steps,
    resolve_expected_fields,
)
from app.services.catalog.naming_compliance import resolve_table_name
from app.services.tia.constants import DEFAULT_PROVIDER


def _field_diff(expected: list[str], actual: list[str]) -> dict[str, list[str]]:
    exp_set = set(expected)
    act_set = set(actual)
    return {
        "missing": sorted(exp_set - act_set),
        "extra": sorted(act_set - exp_set),
    }


def compute_doc_drift(api_name: str, schema_api_fields: list[str]) -> dict[str, Any]:
    expected = resolve_expected_fields(api_name)
    if not expected:
        return {"has_drift": False, "expected_count": 0, "missing": [], "extra": []}
    diff = _field_diff(expected, schema_api_fields)
    return {
        "has_drift": bool(diff["missing"] or diff["extra"]),
        "expected_count": len(expected),
        **diff,
    }


def compute_live_drift(
    schema_api_fields: list[str],
    activation_steps: dict[str, Any] | None,
) -> dict[str, Any]:
    live_fields = live_fields_from_activation_steps(activation_steps)
    if not live_fields:
        return {"has_drift": False, "live_count": 0, "missing": [], "extra": []}
    diff = _field_diff(live_fields, schema_api_fields)
    return {
        "has_drift": bool(diff["missing"] or diff["extra"]),
        "live_count": len(live_fields),
        **diff,
    }


async def compute_ddl_drift(
    session: AsyncSession,
    table_name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    schema_cols = sorted({c["key"] for c in schema.get("columns", []) if c.get("key")})

    def _physical_columns(sync_session) -> set[str]:
        bind = sync_session.get_bind()
        inspector = inspect(bind)
        if table_name not in inspector.get_table_names():
            return set()
        return {c["name"] for c in inspector.get_columns(table_name)}

    physical = sorted(await session.run_sync(_physical_columns))
    if not physical:
        return {
            "has_drift": False,
            "table_exists": False,
            "schema_columns": schema_cols,
            "physical_columns": [],
            "missing": [],
            "extra": [],
        }
    diff = _field_diff(schema_cols, physical)
    return {
        "has_drift": bool(diff["missing"] or diff["extra"]),
        "table_exists": True,
        "schema_columns": schema_cols,
        "physical_columns": physical,
        **diff,
    }


def resolve_drift_status(
    *,
    doc_drift: dict[str, Any],
    live_drift: dict[str, Any],
    ddl_drift: dict[str, Any] | None,
    is_activated: bool,
) -> str:
    if is_activated and ddl_drift and ddl_drift.get("has_drift"):
        return "ddl_drift"
    if live_drift.get("has_drift"):
        return "live_drift"
    if doc_drift.get("has_drift"):
        return "doc_drift"
    return "none"


async def build_drift_report(
    session: AsyncSession,
    *,
    api_name: str,
    data_type: str,
    schema: dict[str, Any],
    activation_steps: dict[str, Any] | None,
    is_activated: bool,
    override_table_name: str | None = None,
    provider_id: str = DEFAULT_PROVIDER,
    last_probe_at: str | None = None,
) -> dict[str, Any]:
    api_fields = list(schema.get("api_fields") or [])
    doc_drift = compute_doc_drift(api_name, api_fields)
    live_drift = compute_live_drift(api_fields, activation_steps)
    ddl_drift = None
    if is_activated:
        table_name = resolve_table_name(
            api_name,
            data_type,
            override_table_name=override_table_name,
            provider_id=provider_id,
        )
        ddl_drift = await compute_ddl_drift(session, table_name, schema)

    drift_status = resolve_drift_status(
        doc_drift=doc_drift,
        live_drift=live_drift,
        ddl_drift=ddl_drift,
        is_activated=is_activated,
    )
    return {
        "drift_status": drift_status,
        "last_probe_at": last_probe_at,
        "doc_drift": doc_drift,
        "live_drift": live_drift,
        "ddl_drift": ddl_drift,
    }
