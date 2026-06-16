"""Auto-create default quality rules when TIA L3 activates a data type."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.quality import QualityRule


class TiaQualitySetupService:
    def setup_default_rules(
        self,
        session: Session,
        data_type: str,
        schema: dict[str, Any],
    ) -> int:
        """Create no_nulls rules for unique keys + row_count rule. Returns rules created."""
        created = 0
        unique_keys = schema.get("unique_keys") or []
        for key in unique_keys:
            name = f"TIA {data_type} {key} not null"
            if self._rule_exists(session, data_type, "no_nulls", key):
                continue
            session.add(
                QualityRule(
                    name=name,
                    rule_type="no_nulls",
                    target_data_type=data_type,
                    config_json={"fields": [key]},
                    is_enabled=True,
                )
            )
            created += 1

        min_rows_name = f"TIA {data_type} min rows"
        if not self._rule_exists(session, data_type, "min_rows", None):
            session.add(
                QualityRule(
                    name=min_rows_name,
                    rule_type="min_rows",
                    target_data_type=data_type,
                    threshold=1,
                    config_json={},
                    is_enabled=True,
                )
            )
            created += 1
        session.flush()
        return created

    def _rule_exists(
        self,
        session: Session,
        data_type: str,
        rule_type: str,
        column: str | None,
    ) -> bool:
        rules = session.execute(
            select(QualityRule).where(
                QualityRule.target_data_type == data_type,
                QualityRule.rule_type == rule_type,
            )
        ).scalars().all()
        for rule in rules:
            cfg = rule.config_json or {}
            if column is None and rule_type in ("row_count", "min_rows"):
                return True
            if cfg.get("column") == column:
                return True
            rule_fields = cfg.get("fields") or []
            if column in rule_fields:
                return True
        return False
