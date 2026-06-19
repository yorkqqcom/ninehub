"""Browser query audit logging with salted universe hash."""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.browser import BrowserQueryAudit
from app.schemas.query_browser import BrowserAuditItem, BrowserAuditListResponse, UniverseSpec


def _audit_salt() -> str:
    return os.environ.get("BROWSER_AUDIT_SALT", "ninehub-browser-audit-dev")


def universe_hash(universe: UniverseSpec) -> str:
    canonical = json.dumps(universe.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    payload = f"{_audit_salt()}:{canonical}"
    return hashlib.sha256(payload.encode()).hexdigest()


class BrowserAuditLogger:
    async def log_query(
        self,
        session: AsyncSession,
        user_id: int | None,
        universe: UniverseSpec,
        indicator_ids: list[str],
        as_of_date: str,
        row_count: int,
        duration_ms: int,
    ) -> None:
        entry = BrowserQueryAudit(
            user_id=user_id,
            universe_hash=universe_hash(universe),
            indicator_ids=indicator_ids,
            as_of_date=as_of_date,
            row_count=row_count,
            duration_ms=duration_ms,
        )
        session.add(entry)
        await session.commit()

    @staticmethod
    def warn_slow(duration_ms: int, details: dict[str, Any] | None = None) -> bool:
        if duration_ms > 3000:
            import logging

            logging.getLogger(__name__).warning(
                "browser slow query %sms %s", duration_ms, details or {}
            )
            return True
        return False

    async def list_audits(
        self,
        session: AsyncSession,
        user_id: int,
        is_admin: bool,
        skip: int = 0,
        limit: int = 50,
    ) -> BrowserAuditListResponse:
        q = select(BrowserQueryAudit)
        count_q = select(func.count()).select_from(BrowserQueryAudit)
        if not is_admin:
            q = q.where(BrowserQueryAudit.user_id == user_id)
            count_q = count_q.where(BrowserQueryAudit.user_id == user_id)
        total = (await session.execute(count_q)).scalar_one()
        rows = (
            await session.execute(
                q.order_by(BrowserQueryAudit.id.desc()).offset(skip).limit(limit)
            )
        ).scalars().all()
        items = [
            BrowserAuditItem(
                id=r.id,
                user_id=r.user_id,
                universe_hash=r.universe_hash,
                indicator_ids=list(r.indicator_ids or []),
                as_of_date=r.as_of_date,
                row_count=r.row_count,
                duration_ms=r.duration_ms,
                created_at=r.created_at,
            )
            for r in rows
        ]
        page = skip // limit + 1 if limit else 1
        return BrowserAuditListResponse(items=items, total=int(total), page=page, size=limit)


class QueryTimer:
    def __init__(self) -> None:
        self._start = time.perf_counter()

    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)
