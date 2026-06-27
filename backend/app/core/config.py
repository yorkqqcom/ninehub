"""Application configuration via environment variables."""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NineHub"
    debug: bool = False
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60 * 24

    database_url: str = "postgresql+asyncpg://ninehub:ninehub@localhost:5432/ninehub"
    sync_database_url: str = "postgresql+psycopg2://ninehub:ninehub@localhost:5432/ninehub"

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_inline_fallback: bool = True

    sync_db_pool_size: int = 10
    sync_db_max_overflow: int = 20

    tushare_token: Optional[str] = None
    tushare_account_points: int = 120
    tushare_max_calls_per_minute: Optional[int] = None
    tushare_dispatch_stagger_seconds: float = 2.0
    tushare_doc_storage_path: Optional[str] = None
    tushare_doc_username: Optional[str] = None
    tushare_doc_password: Optional[str] = None
    tushare_doc_fetch_sleep_seconds: float = 0.35

    sync_start_date: str = "2010-01-01"
    tdx_sidecar_base_url: Optional[str] = None
    tdx_sidecar_api_token: Optional[str] = None
    tdx_install_root: Optional[str] = None
    static_dir: str = "static"
    export_dir: str = "exports"
    export_retention_days: int = 30
    browser_query_cache_ttl: int = 300
    quality_alert_webhook_url: Optional[str] = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
