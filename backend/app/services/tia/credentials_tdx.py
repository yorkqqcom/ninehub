"""Resolve TDX Sidecar credentials from data_sources."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.models.data_source import DataSource


def _paths_from_config(cfg: dict[str, Any]) -> dict[str, Any]:
    paths = dict(cfg.get("paths") or {})
    for key in ("vipdoc_root", "hq_cache_root", "concept_export_dir", "connect_cfg_path"):
        if cfg.get(key) and key not in paths:
            paths[key] = cfg[key]
    return paths


def _credentials_from_source(source: DataSource) -> dict[str, Any] | None:
    cfg = source.config or {}
    base_url = (cfg.get("base_url") or "").strip()
    if not base_url:
        return None
    return {
        "provider": "tdx",
        "base_url": base_url.rstrip("/"),
        "api_token": cfg.get("api_token") or cfg.get("token") or "",
        "install_root": cfg.get("install_root"),
        "import_mode": cfg.get("import_mode") or "file_first",
        "paths": _paths_from_config(cfg),
        "source_id": source.id,
        "source_name": source.name,
        "from_data_source": True,
        "source_config": dict(cfg),
    }


def resolve_tdx_collect_credentials(
    session: Session,
    source_id: int | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    if source_id is not None:
        source = session.get(DataSource, source_id)
        if source is None:
            raise NotFoundError(f"Data source {source_id} not found")
        if source.provider != "tdx":
            raise ValidationError(f"数据源 {source.name} 不是 TDX 类型")
        creds = _credentials_from_source(source)
        if creds is None:
            raise ValidationError(
                f"数据源 {source.name} 未配置 Sidecar base_url",
                details={"field": "config.base_url"},
            )
        return creds

    sources = session.execute(
        select(DataSource)
        .where(DataSource.provider == "tdx", DataSource.status == "active")
        .order_by(DataSource.id.asc())
    ).scalars().all()
    for source in sources:
        creds = _credentials_from_source(source)
        if creds is not None:
            return creds

    env_url = (getattr(settings, "tdx_sidecar_base_url", None) or "").strip()
    if env_url:
        return {
            "provider": "tdx",
            "base_url": env_url.rstrip("/"),
            "api_token": getattr(settings, "tdx_sidecar_api_token", None) or "",
            "install_root": getattr(settings, "tdx_install_root", None),
            "import_mode": "file_first",
            "paths": {},
            "source_id": None,
            "source_name": None,
            "from_data_source": False,
            "source_config": {},
        }
    raise ValidationError(
        "TDX Sidecar 未配置：请在「数据源」创建 TDX 来源并填写 base_url，"
        "或设置环境变量 TDX_SIDECAR_BASE_URL"
    )


def resolve_collect_source_credentials(
    session: Session,
    source_id: int | None = None,
    *,
    data_type: str | None = None,
) -> dict[str, Any]:
    """Pick TDX or Tushare credentials for sync collect."""
    if source_id is not None:
        source = session.get(DataSource, source_id)
        if source is None:
            raise NotFoundError(f"Data source {source_id} not found")
        if source.provider == "tdx":
            return resolve_tdx_collect_credentials(session, source_id)
        from app.services.tia.credentials import resolve_tushare_collect_credentials

        return resolve_tushare_collect_credentials(session, source_id)
    if data_type and data_type.startswith("tdx_"):
        return resolve_tdx_collect_credentials(session, None)
    from app.services.tia.credentials import resolve_tushare_collect_credentials

    return resolve_tushare_collect_credentials(session, None)


def build_sync_auth_extra(creds: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """Merge provider-specific auth fields into SyncContext.extra."""
    provider = str(creds.get("provider") or extra.get("provider") or "tushare")
    extra = dict(extra)
    extra["provider"] = provider
    extra["source_config"] = dict(creds.get("source_config") or extra.get("source_config") or {})
    if provider == "tdx":
        extra["tdx_base_url"] = creds.get("base_url") or extra.get("tdx_base_url")
        extra["tdx_api_token"] = creds.get("api_token") or extra.get("api_token") or ""
        extra["token"] = ""
        return extra
    from app.services.tia.credentials import require_tushare_token

    token = extra.get("token") or creds.get("token")
    if not token:
        token = require_tushare_token(creds)
    extra["token"] = str(token)
    return extra
