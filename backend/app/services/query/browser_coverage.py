"""Table and column coverage for browser indicator data readiness."""

from __future__ import annotations

import re
import time

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_CACHE_TTL_SEC = 3600.0
_row_count_cache: dict[str, tuple[int, float]] = {}
_column_count_cache: dict[str, tuple[dict[str, int], float]] = {}
_IDENT = re.compile(r"^[a-z][a-z0-9_]*$")


class BrowserDataCoverage:
    async def get_table_row_counts(
        self,
        session: AsyncSession,
        table_names: set[str],
    ) -> dict[str, int]:
        now = time.time()
        result: dict[str, int] = {}
        pending: list[str] = []
        for name in table_names:
            if not name:
                continue
            cached = _row_count_cache.get(name)
            if cached and now - cached[1] < _CACHE_TTL_SEC:
                result[name] = cached[0]
            else:
                pending.append(name)
        for name in pending:
            count = await self._count_table(session, name)
            _row_count_cache[name] = (count, now)
            result[name] = count
        return result

    async def get_column_non_null_counts(
        self,
        session: AsyncSession,
        table_columns: dict[str, set[str]],
    ) -> dict[tuple[str, str], int]:
        """Return non-null row counts per (table_name, column_key)."""
        now = time.time()
        result: dict[tuple[str, str], int] = {}
        for table_name, columns in table_columns.items():
            if not table_name or not columns:
                continue
            safe_cols = sorted(c for c in columns if _IDENT.match(c))
            if not safe_cols:
                continue
            cache_key = f"{table_name}:{','.join(safe_cols)}"
            cached = _column_count_cache.get(cache_key)
            if cached and now - cached[1] < _CACHE_TTL_SEC:
                for col, cnt in cached[0].items():
                    result[(table_name, col)] = cnt
                continue
            existing = await self._existing_columns(session, table_name)
            to_query = [c for c in safe_cols if c in existing]
            counts: dict[str, int] = {c: 0 for c in safe_cols}
            if to_query and await self._count_table(session, table_name) > 0:
                parts = [
                    f'COUNT(*) FILTER (WHERE "{c}" IS NOT NULL) AS "{c}"' for c in to_query
                ]
                row = (
                    await session.execute(text(f'SELECT {", ".join(parts)} FROM "{table_name}"'))
                ).one()
                for c in to_query:
                    counts[c] = int(getattr(row, c) or 0)
            _column_count_cache[cache_key] = (counts, now)
            for col, cnt in counts.items():
                result[(table_name, col)] = cnt
        return result

    async def _existing_columns(self, session: AsyncSession, table_name: str) -> set[str]:
        try:
            rows = await session.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t"
                ),
                {"t": table_name},
            )
            return {str(r[0]) for r in rows}
        except Exception:
            return set()

    async def _count_table(self, session: AsyncSession, table_name: str) -> int:
        try:
            row = await session.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
            return int(row.scalar_one())
        except Exception:
            return 0
