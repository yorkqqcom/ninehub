"""Resolve Tushare token and account points for TIA scan probes."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.models.data_source import DataSource
from app.services.tushare.source_quota import resolve_account_points, resolve_max_calls_per_minute


def _credentials_from_source(
    source: DataSource,
    *,
    settings=None,
) -> dict[str, Any] | None:
    settings = settings or get_settings()
    cfg = source.config or {}
    token = cfg.get("token") or settings.tushare_token
    if not token:
        return None
    return {
        "token": token,
        "account_points": resolve_account_points(cfg),
        "max_calls_per_minute": resolve_max_calls_per_minute(cfg),
        "source_id": source.id,
        "source_name": source.name,
        "from_data_source": bool(cfg.get("token")),
        "provider": source.provider,
        "source_config": dict(cfg),
    }


def resolve_tushare_scan_credentials(session: Session) -> dict[str, Any]:
    """Prefer first active Tushare source with a usable token; fallback to environment."""
    settings = get_settings()
    sources = session.execute(
        select(DataSource)
        .where(DataSource.provider == "tushare", DataSource.status == "active")
        .order_by(DataSource.id.asc())
    ).scalars().all()

    for source in sources:
        creds = _credentials_from_source(source, settings=settings)
        if creds is not None:
            return creds

    token = settings.tushare_token or None
    return {
        "token": token,
        "account_points": settings.tushare_account_points,
        "max_calls_per_minute": resolve_max_calls_per_minute(None),
        "source_id": None,
        "source_name": None,
        "from_data_source": False,
        "provider": "tushare",
        "source_config": {},
    }


def resolve_tushare_collect_credentials(
    session: Session,
    source_id: int | None = None,
) -> dict[str, Any]:
    """Resolve credentials for sync collect; auto-pick source when task.source_id is unset."""
    if source_id is not None:
        source = session.get(DataSource, source_id)
        if source is None:
            raise NotFoundError(f"Data source {source_id} not found")
        creds = _credentials_from_source(source)
        if creds is None:
            raise ValidationError(
                f"数据源 {source.name} 未配置 Tushare Token，请在「数据源」页填写或设置 TUSHARE_TOKEN"
            )
        return creds
    return resolve_tushare_scan_credentials(session)


def require_tushare_token(creds: dict[str, Any]) -> str:
    token = creds.get("token")
    if not token:
        raise ValidationError(
            "Tushare Token 未配置：请在「数据源」创建 Tushare 来源并填写 Token，"
            "或设置环境变量 TUSHARE_TOKEN"
        )
    return str(token)
