"""Share-token storage for complex browser queries (Redis, TTL 7d)."""

from __future__ import annotations

import json
import secrets
from typing import Any

from app.services.query.browser_cache import BrowserQueryCache

SHARE_TTL_SEC = 7 * 24 * 3600


class BrowserShareService:
    def __init__(self) -> None:
        self._cache = BrowserQueryCache()

    def create_token(self, payload: dict[str, Any]) -> str:
        token = secrets.token_urlsafe(16)
        self._cache.set(f"share:{token}", payload, ttl_sec=SHARE_TTL_SEC)
        return token

    def get_payload(self, token: str) -> dict[str, Any] | None:
        raw = self._cache.get(f"share:{token}")
        if raw is None:
            return None
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw) if isinstance(raw, str) else None
        except json.JSONDecodeError:
            return None
