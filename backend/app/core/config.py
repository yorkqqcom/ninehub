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

    # Watch / quote_watch (pure TDX)
    watch_tdx_sidecar_url: Optional[str] = None
    watch_tdx_sidecar_token: Optional[str] = None
    watch_alert_retention_days: int = 30
    watch_max_enabled_profiles: int = 50
    watch_max_profiles_per_user: int = 5
    watch_max_targets_per_profile: int = 100
    watch_require_redis_leader: bool = False
    watch_tick_interval_seconds: float = 5.0
    watch_quote_hard_ttl_seconds: float = 2.0
    watch_session_morning_start: str = "09:15"
    watch_session_morning_end: str = "11:30"
    watch_session_afternoon_start: str = "13:00"
    watch_session_afternoon_end: str = "15:05"
    # Optional outbound notify (e.g. Hermes webhook deliver_only).
    # Prefer platform_settings UI/DB; env is fallback when DB pair is unset.
    watch_alert_webhook_url: Optional[str] = None
    watch_alert_webhook_secret: Optional[str] = None
    watch_alert_webhook_timeout_seconds: float = 3.0
    # Hermes Generic V2 (default) or legacy V1 body-only HMAC.
    watch_alert_webhook_signature_version: str = "v2"


@lru_cache
def get_settings() -> Settings:
    return Settings()
