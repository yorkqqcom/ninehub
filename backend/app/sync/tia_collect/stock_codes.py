"""Resolve stock codes for date-range style collection."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

DEFAULT_STOCK_CODES = ["000001.SZ", "600000.SH"]


def resolve_stock_codes(
    session: Session | None,
    extra: dict[str, Any],
    *,
    max_codes: int = 50,
    rotation_offset: int = 0,
) -> tuple[list[str], int]:
    """Return stock codes and next rotation offset for daily batch."""
    explicit = extra.get("stock_codes")
    if explicit:
        codes = list(explicit)[:max_codes]
        return codes, 0

    table_name = extra.get("stock_codes_table") or "tushare_stock_basic"
    if session is not None:
        for column in ("stock_code", "ts_code"):
            try:
                rows = session.execute(
                    text(
                        f"SELECT DISTINCT {column} FROM {table_name} "
                        f"WHERE {column} IS NOT NULL ORDER BY {column}"
                    ),
                ).scalars().all()
                if rows:
                    all_codes = [str(r) for r in rows]
                    if len(all_codes) <= max_codes:
                        return all_codes[:max_codes], 0
                    offset = rotation_offset % len(all_codes)
                    rotated = all_codes[offset:] + all_codes[:offset]
                    selected = rotated[:max_codes]
                    next_offset = (offset + len(selected)) % len(all_codes)
                    return selected, next_offset
            except Exception:
                continue

    return DEFAULT_STOCK_CODES[:max_codes], 0
