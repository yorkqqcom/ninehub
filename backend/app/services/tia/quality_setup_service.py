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
        created += self._setup_tdx_concept_cross_rules(session, data_type)
        session.flush()
        return created

    def _setup_tdx_concept_cross_rules(self, session: Session, data_type: str) -> int:
        """Compare TDX concept tables with Tushare tdx_* reference when both exist."""
        cross_map = {
            "tdx_concept_index": "tushare_tdx_index",
            "tdx_concept_member": "tushare_tdx_member",
        }
        ref_type = cross_map.get(data_type)
        if ref_type is None:
            return 0
        name = f"TDX vs Tushare row count ({data_type})"
        existing = session.execute(
            select(QualityRule).where(
                QualityRule.target_data_type == data_type,
                QualityRule.rule_type == "cross_table_count",
            )
        ).scalar_one_or_none()
        if existing is not None:
            return 0
        session.add(
            QualityRule(
                name=name,
                rule_type="cross_table_count",
                target_data_type=data_type,
                threshold=0.8,
                config_json={
                    "reference_data_type": ref_type,
                    "metric": "row_count_ratio",
                    "note": "TDX 本地概念 vs Tushare tdx_* 行数比（参考）",
                },
                is_enabled=True,
            )
        )
        return 1

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
