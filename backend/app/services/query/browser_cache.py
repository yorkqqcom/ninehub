"""Optional Redis cache for hot browser queries (Phase E)."""

from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings

_memory_store: dict[str, tuple[str, float]] = {}


class BrowserQueryCache:
    """Redis with in-memory fallback for dev/tests."""

    def get(self, key: str) -> Any | None:
        try:
            import redis
            import time

            settings = get_settings()
            url = getattr(settings, "redis_url", None) or "redis://localhost:6379/0"
            client = redis.from_url(url, decode_responses=True, socket_connect_timeout=0.3)
            raw = client.get(f"ninehub:browser:{key}")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
        import time

        item = _memory_store.get(key)
        if not item:
            return None
        raw, expires = item
        if time.time() > expires:
            _memory_store.pop(key, None)
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    def set(self, key: str, value: Any, ttl_sec: int = 3600) -> None:
        payload = json.dumps(value, default=str)
        try:
            import redis

            settings = get_settings()
            url = getattr(settings, "redis_url", None) or "redis://localhost:6379/0"
            client = redis.from_url(url, decode_responses=True, socket_connect_timeout=0.3)
            client.setex(f"ninehub:browser:{key}", ttl_sec, payload)
            return
        except Exception:
            pass
        import time

        _memory_store[key] = (payload, time.time() + ttl_sec)
