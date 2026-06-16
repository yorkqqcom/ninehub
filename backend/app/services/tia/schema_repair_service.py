"""Repair persisted TIA schema + DDL for activated APIs (legacy wrapper)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.tia.schema_maintenance_service import TiaSchemaMaintenanceService


class TiaSchemaRepairService:
    def __init__(self) -> None:
        self._maintenance = TiaSchemaMaintenanceService()

    def repair_api_sync(self, session: Session, api_name: str) -> dict[str, Any]:
        plan = self._maintenance.plan(session, api_name)
        if plan.get("registry_registered"):
            modes: list[str] = ["columns", "unique_keys"]
        elif plan.get("columns_drift"):
            modes = ["columns"]
        else:
            modes = ["columns"]
        return self._maintenance.apply(
            session,
            api_name,
            modes,  # type: ignore[arg-type]
            confirm_risk=True,
        )
