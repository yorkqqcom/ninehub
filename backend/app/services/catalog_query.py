"""Catalog-driven fact table queries (browse + quality checks)."""

from datetime import date
from typing import Any

from sqlalchemy import MetaData, Table, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.catalog.registry import get_data_type_entry


class CatalogQueryService:
    """Query activated catalog data types."""

    def _resolve_filter_column(self, filter_key: str, column_keys: set[str]) -> str | None:
        if filter_key in column_keys:
            return filter_key
        if filter_key == "stock_code" and "ts_code" in column_keys:
            return "ts_code"
        return None

    async def count_rows(
        self,
        session: AsyncSession,
        data_type: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        entry = get_data_type_entry(data_type)
        if entry is None:
            raise ValueError(f"Unknown data_type: {data_type}")
        filters = filters or {}
        return await self._count_dynamic(session, entry.table_name, entry.columns, filters)

    async def fetch_rows(
        self,
        session: AsyncSession,
        data_type: str,
        skip: int = 0,
        limit: int = 500,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        entry = get_data_type_entry(data_type)
        if entry is None:
            raise ValueError(f"Unknown data_type: {data_type}")
        filters = filters or {}
        return await self._fetch_dynamic(
            session, entry.table_name, entry.columns, skip, limit, filters
        )

    async def count_nulls(
        self,
        session: AsyncSession,
        data_type: str,
        fields: list[str],
        filters: dict[str, Any] | None = None,
    ) -> dict[str, int]:
        entry = get_data_type_entry(data_type)
        if entry is None:
            raise ValueError(f"Unknown data_type: {data_type}")
        if not entry.table_name:
            return {field: 0 for field in fields}
        table = await self._reflect_table_async(session, entry.table_name)
        query, null_counts, label_to_field = self._build_null_count_query(
            table, entry.columns, fields, filters or {}
        )
        if query is None:
            return null_counts
        row = (await session.execute(query)).one()
        return self._apply_null_count_row(null_counts, label_to_field, row)

    def count_nulls_sync(
        self,
        session: Session,
        data_type: str,
        fields: list[str],
        filters: dict[str, Any] | None = None,
    ) -> dict[str, int]:
        entry = get_data_type_entry(data_type)
        if entry is None:
            raise ValueError(f"Unknown data_type: {data_type}")
        if not entry.table_name:
            return {field: 0 for field in fields}
        bind = session.get_bind()
        table = self._reflect_table(bind, entry.table_name)
        query, null_counts, label_to_field = self._build_null_count_query(
            table, entry.columns, fields, filters or {}
        )
        if query is None:
            return null_counts
        row = session.execute(query).one()
        return self._apply_null_count_row(null_counts, label_to_field, row)

    def count_rows_sync(
        self,
        session: Session,
        data_type: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        entry = get_data_type_entry(data_type)
        if entry is None:
            raise ValueError(f"Unknown data_type: {data_type}")
        filters = filters or {}
        if not entry.table_name:
            return 0
        bind = session.get_bind()
        table = self._reflect_table(bind, entry.table_name)
        clauses = self._dynamic_clauses(table, entry.columns, filters)
        count_q = select(func.count()).select_from(table)
        for clause in clauses:
            count_q = count_q.where(clause)
        return session.execute(count_q).scalar_one()

    def fetch_rows_sync(
        self,
        session: Session,
        data_type: str,
        skip: int = 0,
        limit: int = 500,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        entry = get_data_type_entry(data_type)
        if entry is None:
            raise ValueError(f"Unknown data_type: {data_type}")
        filters = filters or {}
        if not entry.table_name:
            return []
        bind = session.get_bind()
        table = self._reflect_table(bind, entry.table_name)
        clauses = self._dynamic_clauses(table, entry.columns, filters)
        query = select(table)
        for clause in clauses:
            query = query.where(clause)
        order_col = self._order_column(table, entry.columns)
        if order_col is not None:
            query = query.order_by(order_col.desc())
        rows = session.execute(query.offset(skip).limit(limit)).mappings().all()
        return [self._serialize_row(dict(r)) for r in rows]

    def _build_null_count_query(
        self,
        table: Table,
        columns,
        fields: list[str],
        filters: dict[str, Any],
    ) -> tuple[Any | None, dict[str, int], dict[str, str]]:
        column_keys = {c.key for c in columns}
        table_keys = set(table.c.keys())
        clauses = self._dynamic_clauses(table, columns, filters)
        null_counts: dict[str, int] = {field: 0 for field in fields}
        aggregates = []
        label_to_field: dict[str, str] = {}
        for field in fields:
            resolved = self._resolve_filter_column(field, column_keys & table_keys)
            if resolved is None:
                continue
            label = f"null_{field}"
            aggregates.append(
                func.coalesce(
                    func.sum(case((table.c[resolved].is_(None), 1), else_=0)),
                    0,
                ).label(label)
            )
            label_to_field[label] = field
        if not aggregates:
            return None, null_counts, {}
        query = select(*aggregates).select_from(table)
        for clause in clauses:
            query = query.where(clause)
        return query, null_counts, label_to_field

    def _apply_null_count_row(
        self,
        null_counts: dict[str, int],
        label_to_field: dict[str, str],
        row: Any,
    ) -> dict[str, int]:
        result = dict(null_counts)
        for label, field in label_to_field.items():
            result[field] = int(row._mapping[label] or 0)
        return result

    async def _count_dynamic(
        self,
        session: AsyncSession,
        table_name: str | None,
        columns,
        filters: dict[str, Any],
    ) -> int:
        if not table_name:
            return 0
        table = await self._reflect_table_async(session, table_name)
        clauses = self._dynamic_clauses(table, columns, filters)
        count_q = select(func.count()).select_from(table)
        for clause in clauses:
            count_q = count_q.where(clause)
        return (await session.execute(count_q)).scalar_one()

    async def _fetch_dynamic(
        self,
        session: AsyncSession,
        table_name: str | None,
        columns,
        skip: int,
        limit: int,
        filters: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not table_name:
            return []
        table = await self._reflect_table_async(session, table_name)
        clauses = self._dynamic_clauses(table, columns, filters)
        query = select(table)
        for clause in clauses:
            query = query.where(clause)
        order_col = self._order_column(table, columns)
        if order_col is not None:
            query = query.order_by(order_col.desc())
        rows = (await session.execute(query.offset(skip).limit(limit))).mappings().all()
        return [self._serialize_row(dict(r)) for r in rows]

    async def _reflect_table_async(self, session: AsyncSession, table_name: str) -> Table:
        conn = await session.connection()

        def _load(sync_conn) -> Table:
            metadata = MetaData()
            return Table(table_name, metadata, autoload_with=sync_conn)

        return await conn.run_sync(_load)

    def _reflect_table(self, bind, table_name: str) -> Table:
        metadata = MetaData()
        return Table(table_name, metadata, autoload_with=bind)

    def _dynamic_clauses(self, table: Table, columns, filters: dict[str, Any]) -> list[Any]:
        column_keys = {c.key for c in columns}
        table_keys = set(table.c.keys())
        clauses: list[Any] = []
        stock_col = self._resolve_filter_column("stock_code", column_keys & table_keys)
        if filters.get("stock_code") and stock_col:
            clauses.append(table.c[stock_col] == filters["stock_code"])
        for date_key in ("trade_date", "end_date", "ann_date"):
            resolved = self._resolve_filter_column(date_key, column_keys & table_keys)
            if not resolved:
                continue
            if filters.get("start_date"):
                clauses.append(table.c[resolved] >= date.fromisoformat(filters["start_date"]))
            if filters.get("end_date"):
                clauses.append(table.c[resolved] <= date.fromisoformat(filters["end_date"]))
            break
        return clauses

    def _order_column(self, table: Table, columns):
        for key in ("trade_date", "end_date", "ann_date", "id"):
            if key in table.c:
                return table.c[key]
        return None

    def _serialize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, val in row.items():
            if key == "id" or key == "created_at":
                continue
            if hasattr(val, "isoformat"):
                out[key] = val.isoformat()
            elif val is not None and hasattr(val, "__float__"):
                try:
                    out[key] = float(val)
                except (TypeError, ValueError):
                    out[key] = val
            else:
                out[key] = val
            if key == "ts_code" and "stock_code" not in out:
                out["stock_code"] = val
        return out
