"""Runtime DDL for TIA fact tables (L3 run_migration step)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError

_TYPE_MAP = {
    "string": String(128),
    "text": Text(),
    "number": Numeric(20, 4),
    "date": Date(),
}


def _sqlalchemy_column(col: dict[str, Any]) -> Column:
    col_type = _TYPE_MAP.get(col.get("type", "string"), String(128))
    nullable = col.get("nullable", True)
    return Column(col["key"], col_type, nullable=nullable)


def _sync_text_column_types(
    session: Session,
    table_name: str,
    columns: list[dict[str, Any]],
    existing_columns: list[dict[str, Any]],
) -> list[str]:
    """Widen VARCHAR columns to TEXT when schema marks them as long text."""
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return []
    existing_by_name = {c["name"]: c for c in existing_columns}
    widened: list[str] = []
    for col in columns:
        key = col["key"]
        if col.get("type") != "text" or key not in existing_by_name:
            continue
        current = str(existing_by_name[key]["type"]).upper()
        if "TEXT" in current:
            continue
        session.execute(text(f'ALTER TABLE "{table_name}" ALTER COLUMN "{key}" TYPE TEXT'))
        widened.append(key)
    return widened


def _resolve_unique_keys(schema: dict[str, Any]) -> list[str]:
    columns = schema.get("columns") or []
    col_keys = {c["key"] for c in columns}
    return [k for k in (schema.get("unique_keys") or []) if k in col_keys]


def _sync_indexes(
    session: Session,
    table_name: str,
    schema: dict[str, Any],
    *,
    existing_cols: set[str],
) -> dict[str, Any]:
    """Ensure unique + browse indexes from schema.indexes metadata."""
    bind = session.get_bind()
    inspector = inspect(bind)
    indexes = schema.get("indexes") or []
    if not indexes:
        unique_keys = _resolve_unique_keys(schema)
        if unique_keys:
            from app.services.tia.unique_key_registry import build_schema_indexes

            indexes = build_schema_indexes(schema, table_name)

    existing_index_names = {idx["name"] for idx in inspector.get_indexes(table_name)}
    unique_created = False
    browse_created: list[str] = []

    for idx in indexes:
        name = idx.get("name")
        cols = [c for c in (idx.get("columns") or []) if c in existing_cols]
        if not name or not cols:
            continue
        if name in existing_index_names:
            continue
        cols_sql = ", ".join(f'"{c}"' for c in cols)
        unique_sql = "UNIQUE " if idx.get("unique") else ""
        session.execute(
            text(f'CREATE {unique_sql}INDEX IF NOT EXISTS "{name}" ON "{table_name}" ({cols_sql})')
        )
        existing_index_names.add(name)
        if idx.get("unique"):
            unique_created = True
        else:
            browse_created.append(name)

    return {"unique_index_created": unique_created, "browse_indexes_created": browse_created}


def sync_unique_constraint(
    session: Session,
    table_name: str,
    old_schema: dict[str, Any] | None,
    new_schema: dict[str, Any],
    *,
    confirm_risk: bool = False,
) -> dict[str, Any]:
    """Replace unique constraint/index when business keys change (PostgreSQL)."""
    old_keys = list((old_schema or {}).get("unique_keys") or [])
    new_keys = _resolve_unique_keys(new_schema)
    result: dict[str, Any] = {
        "unique_keys_before": old_keys,
        "unique_keys_after": new_keys,
        "unique_constraint_dropped": False,
        "unique_index_dropped": [],
        "unique_constraint_created": False,
        "unique_index_created": False,
    }
    if old_keys == new_keys:
        return result

    if not confirm_risk:
        raise ValidationError(
            "Unique keys changed; set confirm_risk=true to replace DB constraints"
        )

    bind = session.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return result

    existing_cols = {c["name"] for c in inspector.get_columns(table_name)}

    if bind.dialect.name == "postgresql":
        old_uq = (old_schema or {}).get("unique_constraint") or {}
        old_uq_name = old_uq.get("name")
        if old_uq_name:
            session.execute(
                text(f'ALTER TABLE "{table_name}" DROP CONSTRAINT IF EXISTS "{old_uq_name}"')
            )
            result["unique_constraint_dropped"] = True

        for idx in (old_schema or {}).get("indexes") or []:
            if not idx.get("unique"):
                continue
            idx_name = idx.get("name")
            if idx_name and idx_name in {i["name"] for i in inspector.get_indexes(table_name)}:
                session.execute(text(f'DROP INDEX IF EXISTS "{idx_name}"'))
                result["unique_index_dropped"].append(idx_name)

        for idx in inspector.get_indexes(table_name):
            if idx.get("unique") and set(idx.get("column_names") or []) == set(old_keys):
                session.execute(text(f'DROP INDEX IF EXISTS "{idx["name"]}"'))
                result["unique_index_dropped"].append(idx["name"])

    idx_sync = _sync_indexes(
        session,
        table_name,
        new_schema,
        existing_cols=existing_cols,
    )
    constraint_created = _ensure_unique_constraint(
        session, table_name, new_schema, existing_cols=existing_cols
    )
    result["unique_constraint_created"] = constraint_created
    result["unique_index_created"] = bool(idx_sync.get("unique_index_created"))
    return result


def _ensure_unique_constraint(
    session: Session,
    table_name: str,
    schema: dict[str, Any],
    *,
    existing_cols: set[str],
) -> bool:
    """Add named UNIQUE constraint on PostgreSQL when missing (legacy tables)."""
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return False

    unique_keys = _resolve_unique_keys(schema)
    if not unique_keys or not all(k in existing_cols for k in unique_keys):
        return False

    uq_meta = schema.get("unique_constraint") or {}
    uq_name = uq_meta.get("name")
    if not uq_name:
        from app.services.tia.unique_key_registry import unique_constraint_name

        uq_name = unique_constraint_name(table_name, unique_keys)

    exists = session.execute(
        text(
            """
            SELECT 1 FROM pg_catalog.pg_constraint c
            JOIN pg_catalog.pg_class t ON c.conrelid = t.oid
            JOIN pg_catalog.pg_namespace n ON t.relnamespace = n.oid
            WHERE t.relname = :tbl AND c.conname = :cn AND c.contype = 'u'
            """
        ),
        {"tbl": table_name, "cn": uq_name},
    ).scalar()
    if exists:
        return False

    cols_sql = ", ".join(f'"{k}"' for k in unique_keys)
    nested = session.begin_nested()
    try:
        session.execute(
            text(f'ALTER TABLE "{table_name}" ADD CONSTRAINT "{uq_name}" UNIQUE ({cols_sql})')
        )
        nested.commit()
        return True
    except Exception:
        nested.rollback()
        return False


class TiaMigrationService:
    """Create TIA fact tables at activation time (idempotent)."""

    def ensure_table(self, session: Session, table_name: str, schema: dict[str, Any]) -> bool:
        """Create table if missing. Returns True if newly created."""
        if not table_name or not table_name.replace("_", "").isalnum():
            raise ValidationError(f"Invalid table name: {table_name}")
        columns = schema.get("columns") or []
        if not columns:
            raise ValidationError("Schema must include columns")

        bind = session.get_bind()
        inspector = inspect(bind)
        if table_name in inspector.get_table_names():
            return False

        metadata = MetaData()
        sa_columns = [Column("id", Integer, primary_key=True, autoincrement=True)]
        sa_columns.extend(_sqlalchemy_column(c) for c in columns)
        sa_columns.append(
            Column("created_at", DateTime(timezone=True), server_default=text("CURRENT_TIMESTAMP"))
        )
        unique_keys = _resolve_unique_keys(schema)
        constraints: tuple = ()
        if unique_keys:
            uq_meta = schema.get("unique_constraint") or {}
            uq_name = uq_meta.get("name")
            if not uq_name:
                from app.services.tia.unique_key_registry import unique_constraint_name

                uq_name = unique_constraint_name(table_name, unique_keys)
            constraints = (UniqueConstraint(*unique_keys, name=uq_name),)
        Table(table_name, metadata, *sa_columns, *constraints)
        metadata.create_all(bind)
        _sync_indexes(session, table_name, schema, existing_cols={c["key"] for c in columns})
        _ensure_unique_constraint(
            session, table_name, schema, existing_cols={c["key"] for c in columns}
        )
        return True

    def sync_table_schema(
        self,
        session: Session,
        table_name: str,
        schema: dict[str, Any],
        *,
        old_schema: dict[str, Any] | None = None,
        confirm_risk: bool = False,
        sync_columns: bool = True,
        sync_unique: bool = True,
    ) -> dict[str, Any]:
        """Add missing columns and unique index for an existing TIA table."""
        if not table_name or not table_name.replace("_", "").isalnum():
            raise ValidationError(f"Invalid table name: {table_name}")
        columns = schema.get("columns") or []
        if not columns:
            raise ValidationError("Schema must include columns")

        bind = session.get_bind()
        inspector = inspect(bind)
        if table_name not in inspector.get_table_names():
            return {
                "columns_added": [],
                "columns_dropped": [],
                "columns_widened": [],
                "unique_index_created": False,
                "unique_constraint_created": False,
                "browse_indexes_created": [],
                "unique_constraint_sync": {},
            }

        existing_cols = {c["name"] for c in inspector.get_columns(table_name)}
        existing_column_meta = inspector.get_columns(table_name)
        added: list[str] = []
        dropped: list[str] = []
        widened: list[str] = []

        if sync_columns:
            for col in columns:
                key = col["key"]
                if key in existing_cols:
                    continue
                sa_col = _sqlalchemy_column(col)
                col_type = sa_col.type.compile(dialect=bind.dialect)
                nullable_sql = "" if col.get("nullable", True) else " NOT NULL"
                session.execute(
                    text(f'ALTER TABLE "{table_name}" ADD COLUMN "{key}" {col_type}{nullable_sql}')
                )
                added.append(key)
                existing_cols.add(key)

            widened = _sync_text_column_types(
                session, table_name, columns, existing_column_meta
            )

            schema_keys = {c["key"] for c in columns}
            preserved = schema_keys | {"id", "created_at", "updated_at"}
            would_drop: list[str] = []
            if bind.dialect.name == "postgresql":
                for col in inspector.get_columns(table_name):
                    name = col["name"]
                    if name in preserved:
                        continue
                    would_drop.append(name)

            if would_drop and not confirm_risk:
                raise ValidationError(
                    "Column drops pending; set confirm_risk=true to apply schema maintenance"
                )

            if bind.dialect.name == "postgresql":
                for name in would_drop:
                    session.execute(
                        text(f'ALTER TABLE "{table_name}" DROP COLUMN IF EXISTS "{name}"')
                    )
                    dropped.append(name)
                    existing_cols.discard(name)

        idx_sync: dict[str, Any] = {"unique_index_created": False, "browse_indexes_created": []}
        constraint_created = False
        constraint_sync: dict[str, Any] = {}

        if sync_unique:
            old_keys = list((old_schema or {}).get("unique_keys") or [])
            new_keys = _resolve_unique_keys(schema)
            if old_keys and old_keys != new_keys:
                constraint_sync = sync_unique_constraint(
                    session,
                    table_name,
                    old_schema,
                    schema,
                    confirm_risk=confirm_risk,
                )
            else:
                idx_sync = _sync_indexes(
                    session,
                    table_name,
                    schema,
                    existing_cols=existing_cols,
                )
                constraint_created = _ensure_unique_constraint(
                    session, table_name, schema, existing_cols=existing_cols
                )
        elif sync_columns:
            idx_sync = _sync_indexes(
                session,
                table_name,
                schema,
                existing_cols=existing_cols,
            )
            constraint_created = _ensure_unique_constraint(
                session, table_name, schema, existing_cols=existing_cols
            )

        return {
            "columns_added": added,
            "columns_dropped": dropped,
            "columns_widened": widened,
            "unique_index_created": bool(
                idx_sync.get("unique_index_created")
                or constraint_sync.get("unique_index_created")
            ),
            "unique_constraint_created": constraint_created
            or bool(constraint_sync.get("unique_constraint_created")),
            "browse_indexes_created": idx_sync.get("browse_indexes_created") or [],
            "unique_constraint_sync": constraint_sync,
        }
