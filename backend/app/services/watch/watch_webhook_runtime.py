"""In-process watch alert webhook config (DB > env; hot-applied after commit)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal, Optional

from app.core.config import get_settings

logger = logging.getLogger(__name__)

ActiveSource = Literal["db", "env", "none"]


@dataclass(frozen=True)
class WatchWebhookSnapshot:
    url: str
    secret: str
    signature_version: str
    source: ActiveSource

    @property
    def configured(self) -> bool:
        return self.source != "none" and bool(self.url and self.secret)


def _strip(value: Optional[str]) -> str:
    return (value or "").strip()


def resolve_watch_webhook(
    *,
    db_url: Optional[str] = None,
    db_secret: Optional[str] = None,
    db_version: Optional[str] = None,
    env_url: Optional[str] = None,
    env_secret: Optional[str] = None,
    env_version: Optional[str] = None,
) -> WatchWebhookSnapshot:
    """DB pair wins; incomplete DB does not block env fallback."""
    d_url, d_secret = _strip(db_url), _strip(db_secret)
    e_url, e_secret = _strip(env_url), _strip(env_secret)
    d_ver = (_strip(db_version) or "v2").lower()
    e_ver = (_strip(env_version) or "v2").lower()

    if d_url and d_secret:
        return WatchWebhookSnapshot(
            url=d_url,
            secret=d_secret,
            signature_version=d_ver if d_ver in ("v1", "v2") else "v2",
            source="db",
        )
    if d_url or d_secret:
        logger.warning(
            "incomplete db watch_alert_webhook config (url_set=%s secret_set=%s); fall through to env",
            bool(d_url),
            bool(d_secret),
        )
    if e_url and e_secret:
        return WatchWebhookSnapshot(
            url=e_url,
            secret=e_secret,
            signature_version=e_ver if e_ver in ("v1", "v2") else "v2",
            source="env",
        )
    if e_url or e_secret:
        logger.error(
            "incomplete env watch_alert_webhook config (url_set=%s secret_set=%s); skip",
            bool(e_url),
            bool(e_secret),
        )
    return WatchWebhookSnapshot(url="", secret="", signature_version="v2", source="none")


def resolve_from_env() -> WatchWebhookSnapshot:
    settings = get_settings()
    return resolve_watch_webhook(
        env_url=settings.watch_alert_webhook_url,
        env_secret=settings.watch_alert_webhook_secret,
        env_version=settings.watch_alert_webhook_signature_version,
    )


def resolve_from_db_row(row: Any | None) -> WatchWebhookSnapshot:
    settings = get_settings()
    if row is None:
        return resolve_from_env()
    return resolve_watch_webhook(
        db_url=getattr(row, "watch_alert_webhook_url", None),
        db_secret=getattr(row, "watch_alert_webhook_secret", None),
        db_version=getattr(row, "watch_alert_webhook_signature_version", None),
        env_url=settings.watch_alert_webhook_url,
        env_secret=settings.watch_alert_webhook_secret,
        env_version=settings.watch_alert_webhook_signature_version,
    )


class WatchWebhookRuntime:
    """Process-local snapshot; replace atomically after successful DB commit."""

    def __init__(self) -> None:
        self._snapshot: WatchWebhookSnapshot = WatchWebhookSnapshot(
            url="", secret="", signature_version="v2", source="none"
        )

    def get(self) -> WatchWebhookSnapshot:
        return self._snapshot

    def apply(self, snapshot: WatchWebhookSnapshot) -> None:
        self._snapshot = snapshot

    def reset(self) -> None:
        self._snapshot = WatchWebhookSnapshot(
            url="", secret="", signature_version="v2", source="none"
        )

    def set_for_tests(
        self,
        *,
        url: str = "",
        secret: str = "",
        signature_version: str = "v2",
        source: ActiveSource = "db",
    ) -> None:
        if url and secret:
            self._snapshot = WatchWebhookSnapshot(
                url=url.strip(),
                secret=secret.strip(),
                signature_version=(signature_version or "v2").strip().lower(),
                source=source if source != "none" else "db",
            )
        else:
            self.reset()

    def reload_from_env(self) -> WatchWebhookSnapshot:
        snap = resolve_from_env()
        self.apply(snap)
        return snap


_runtime = WatchWebhookRuntime()


def get_watch_webhook_runtime() -> WatchWebhookRuntime:
    return _runtime


def env_webhook_configured() -> bool:
    settings = get_settings()
    return bool(
        _strip(settings.watch_alert_webhook_url) and _strip(settings.watch_alert_webhook_secret)
    )
