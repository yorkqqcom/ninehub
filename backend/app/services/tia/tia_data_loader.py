"""Generic upsert into TIA runtime fact tables."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
from sqlalchemy import MetaData, Table, and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.services.catalog.canonical_standard import apply_dataframe_field_mappings
from app.services.tia.unique_key_registry import API_UNIQUE_KEY_OVERRIDES


def _resolve_unique_keys(schema: dict[str, Any]) -> list[str]:
    api_name = schema.get("api_name")
    if api_name and api_name in API_UNIQUE_KEY_OVERRIDES:
        return list(API_UNIQUE_KEY_OVERRIDES[api_name])
    return list(schema.get("unique_keys") or [])


def _normalize_value(value: Any, col_type: str) -> Any:
    if isinstance(value, pd.Series):
        value = value.iloc[0] if len(value) else None
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if col_type == "date":
        if isinstance(value, date):
            return value
        s = str(value).replace("-", "")[:8]
        if len(s) == 8:
            return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        return None
    if col_type == "number":
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    return str(value)


def _reflect_table(session: Session, table_name: str) -> Table:
    """Reflect on a standalone connection so introspection cannot poison the upsert session."""
    metadata = MetaData()
    engine = session.get_bind()
    with engine.connect() as conn:
        return Table(table_name, metadata, autoload_with=conn)


class TiaDataLoader:
    def upsert_dataframe(
        self,
        session: Session,
        table_name: str,
        schema: dict[str, Any],
        df: pd.DataFrame,
    ) -> int:
        if df is None or df.empty:
            return 0
        session.rollback()
        df = apply_dataframe_field_mappings(df, schema)
        unique_keys = _resolve_unique_keys(schema)
        col_meta = {c["key"]: c for c in schema.get("columns", [])}
        if not unique_keys:
            raise ValidationError("Schema unique_keys required for upsert")

        bind = session.get_bind()
        dialect = bind.dialect.name if bind is not None else "postgresql"
        table = _reflect_table(session, table_name)
        count = 0
        skipped_missing_key = 0

        for _, row in df.iterrows():
            record: dict[str, Any] = {}
            for key, meta in col_meta.items():
                src = key
                api_field = meta.get("api_field")
                if key not in df.columns and api_field and api_field in df.columns:
                    src = api_field
                if src not in df.columns:
                    continue
                record[key] = _normalize_value(row[src], meta.get("type", "string"))
            if not record:
                continue
            if any(record.get(uk) is None for uk in unique_keys):
                skipped_missing_key += 1
                continue

            if dialect == "postgresql" and unique_keys:
                stmt = pg_insert(table).values(**record)
                update_cols = {k: stmt.excluded[k] for k in record if k not in unique_keys}
                # index_elements 兼容「仅有唯一索引」的旧表；ON CONSTRAINT 要求具名约束
                conflict_kw: dict[str, Any] = {"index_elements": unique_keys}
                if update_cols:
                    stmt = stmt.on_conflict_do_update(set_=update_cols, **conflict_kw)
                else:
                    stmt = stmt.on_conflict_do_nothing(**conflict_kw)
                session.execute(stmt)
            else:
                clauses = [table.c[uk] == record[uk] for uk in unique_keys if uk in record]
                if clauses:
                    existing = session.execute(select(table).where(and_(*clauses))).first()
                    if existing:
                        session.execute(table.update().where(and_(*clauses)).values(**record))
                    else:
                        session.execute(table.insert().values(**record))
                else:
                    session.execute(table.insert().values(**record))
            count += 1

        if skipped_missing_key and count == 0 and len(df) > 0:
            raise ValidationError(
                f"All {len(df)} rows missing unique key values "
                f"({', '.join(unique_keys)}); check field_mappings"
            )

        session.flush()
        return count
