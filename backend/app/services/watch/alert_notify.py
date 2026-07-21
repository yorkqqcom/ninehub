"""Best-effort outbound notify for watch quote_alert (e.g. Hermes webhook).

Unlike quality_alert_webhook (bare POST), Hermes requires HMAC. Default Generic V2.
Config comes from WatchWebhookRuntime (DB pair > env pair). Failures are logged only
— never raised into WatchTicker.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Mapping

import httpx

from app.core.config import get_settings
from app.services.watch.watch_webhook_runtime import (
    WatchWebhookSnapshot,
    get_watch_webhook_runtime,
)

logger = logging.getLogger(__name__)

_MESSAGE_MAX = 500
_PAYLOAD_KEYS = (
    "alert_id",
    "event_type",
    "symbol",
    "rule_id",
    "message",
    "profile_id",
    "user_id",
    "triggered_at",
)


def build_alert_payload(
    *,
    alert_id: int,
    event_type: str,
    symbol: str,
    rule_id: str,
    message: str,
    profile_id: int,
    user_id: int,
    triggered_at: str | None = None,
) -> dict[str, Any]:
    """Fixed key order; no raw floats; message truncated."""
    ts = triggered_at or datetime.now(timezone.utc).isoformat()
    raw_msg = message or ""
    payload = {
        "alert_id": int(alert_id),
        "event_type": str(event_type),
        "symbol": str(symbol),
        "rule_id": str(rule_id),
        "message": raw_msg[:_MESSAGE_MAX],
        "profile_id": int(profile_id),
        "user_id": int(user_id),
        "triggered_at": ts,
    }
    # Guarantee key order for stable HMAC body
    return {k: payload[k] for k in _PAYLOAD_KEYS}


def encode_alert_body(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sign_webhook(
    body: bytes,
    *,
    secret: str,
    version: str,
    timestamp: str | None = None,
) -> tuple[dict[str, str], str | None]:
    """Return (extra_headers, timestamp_used_for_v2).

    V2: HMAC-SHA256 hex of ``{timestamp}.{body}`` (no sha256= prefix).
    V1: HMAC-SHA256 hex of body only.
    """
    ver = (version or "v2").strip().lower()
    key = secret.encode("utf-8")
    if ver == "v1":
        sig = hmac.new(key, body, hashlib.sha256).hexdigest()
        return {"X-Webhook-Signature": sig}, None
    if ver != "v2":
        raise ValueError(f"unsupported webhook signature version: {version!r}")
    ts = timestamp if timestamp is not None else str(int(time.time()))
    signed = ts.encode("utf-8") + b"." + body
    sig = hmac.new(key, signed, hashlib.sha256).hexdigest()
    return {
        "X-Webhook-Signature-V2": sig,
        "X-Webhook-Timestamp": ts,
    }, ts


def snapshot_from_event(event: Any) -> dict[str, Any] | None:
    """Build notify dict from a flushed WatchAlertEvent; None if not quote_alert."""
    if getattr(event, "event_type", None) != "quote_alert":
        return None
    payload_json = getattr(event, "payload_json", None) or {}
    message = ""
    if isinstance(payload_json, dict):
        message = str(payload_json.get("message") or "")
    created = getattr(event, "created_at", None)
    if created is not None and hasattr(created, "isoformat"):
        triggered_at = created.isoformat()
    else:
        triggered_at = datetime.now(timezone.utc).isoformat()
    return {
        "alert_id": int(event.id),
        "event_type": "quote_alert",
        "symbol": str(event.symbol or ""),
        "rule_id": str(event.rule_id or ""),
        "message": message,
        "profile_id": int(event.profile_id),
        "user_id": int(event.user_id),
        "triggered_at": triggered_at,
    }


def _coerce_snapshot(settings: Any | None) -> WatchWebhookSnapshot | None:
    """Resolve config: explicit settings-like object, else Runtime."""
    if settings is not None:
        url = (getattr(settings, "watch_alert_webhook_url", None) or "").strip()
        secret = (getattr(settings, "watch_alert_webhook_secret", None) or "").strip()
        version = (
            getattr(settings, "watch_alert_webhook_signature_version", None) or "v2"
        ).strip().lower()
        if url and secret:
            return WatchWebhookSnapshot(
                url=url,
                secret=secret,
                signature_version=version if version in ("v1", "v2") else "v2",
                source="db",
            )
        return None
    snap = get_watch_webhook_runtime().get()
    return snap if snap.configured else None


async def notify_quote_alert(snapshot: Mapping[str, Any]) -> None:
    """POST one alert to configured webhook. Never raises to caller."""
    cfg = _coerce_snapshot(None)
    if cfg is None:
        return

    version = (cfg.signature_version or "v2").strip().lower()
    if version not in ("v1", "v2"):
        logger.error("invalid watch_alert_webhook_signature_version=%s; skip notify", version)
        return
    if version == "v1":
        logger.warning(
            "watch_alert_webhook using legacy V1 HMAC (replay-prone); upgrade Hermes and set "
            "signature_version=v2"
        )

    url = cfg.url
    secret = cfg.secret
    payload = build_alert_payload(
        alert_id=int(snapshot["alert_id"]),
        event_type=str(snapshot.get("event_type") or "quote_alert"),
        symbol=str(snapshot.get("symbol") or ""),
        rule_id=str(snapshot.get("rule_id") or ""),
        message=str(snapshot.get("message") or ""),
        profile_id=int(snapshot["profile_id"]),
        user_id=int(snapshot["user_id"]),
        triggered_at=snapshot.get("triggered_at"),
    )
    body = encode_alert_body(payload)
    sig_headers, _ = sign_webhook(body, secret=secret, version=version)
    headers = {
        "Content-Type": "application/json",
        "X-Request-ID": str(payload["alert_id"]),
        **sig_headers,
    }
    timeout = float(get_settings().watch_alert_webhook_timeout_seconds)
    try:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            resp = await client.post(url, content=body, headers=headers, timeout=timeout)
        if resp.status_code >= 300:
            logger.warning(
                "watch_alert_webhook_failed alert_id=%s status_code=%s",
                payload["alert_id"],
                resp.status_code,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "watch_alert_webhook_failed alert_id=%s exc_type=%s detail=%s",
            payload.get("alert_id"),
            type(exc).__name__,
            exc,
        )


async def post_watch_alert_webhook_test() -> dict[str, Any]:
    """Send a signed test payload using current Runtime. Never raises."""
    cfg = get_watch_webhook_runtime().get()
    if not cfg.configured:
        return {
            "ok": False,
            "status_code": None,
            "active_source": cfg.source,
            "detail": "webhook not configured",
        }
    version = (cfg.signature_version or "v2").strip().lower()
    if version not in ("v1", "v2"):
        return {
            "ok": False,
            "status_code": None,
            "active_source": cfg.source,
            "detail": f"invalid signature_version={version}",
        }
    payload = build_alert_payload(
        alert_id=0,
        event_type="quote_alert",
        symbol="000000.SZ",
        rule_id="ninehub_test",
        message="NineHub watch alert webhook test",
        profile_id=0,
        user_id=0,
    )
    body = encode_alert_body(payload)
    sig_headers, _ = sign_webhook(body, secret=cfg.secret, version=version)
    headers = {
        "Content-Type": "application/json",
        "X-Request-ID": "0",
        **sig_headers,
    }
    timeout = float(get_settings().watch_alert_webhook_timeout_seconds)
    try:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            resp = await client.post(cfg.url, content=body, headers=headers, timeout=timeout)
        ok = resp.status_code < 300
        return {
            "ok": ok,
            "status_code": resp.status_code,
            "active_source": cfg.source,
            "detail": "ok" if ok else f"HTTP {resp.status_code}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status_code": None,
            "active_source": cfg.source,
            "detail": f"{type(exc).__name__}: {exc}",
        }


def is_watch_alert_webhook_configured(settings: Any | None = None) -> bool:
    """True when url+secret pair is available (Runtime by default)."""
    if settings is not None:
        url = (getattr(settings, "watch_alert_webhook_url", None) or "").strip()
        secret = (getattr(settings, "watch_alert_webhook_secret", None) or "").strip()
        return bool(url and secret)
    return get_watch_webhook_runtime().get().configured
