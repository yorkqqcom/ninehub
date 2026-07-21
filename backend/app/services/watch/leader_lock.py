"""Redis leader lock for WatchTicker."""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_KEY = "ninehub:watch:ticker:leader"


def _token_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode()
    return str(value)


class LeaderLock:
    def __init__(self, redis_url: str, *, ttl_seconds: int = 15) -> None:
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self.token = uuid.uuid4().hex
        self._client: Any = None

    def _conn(self):
        if self._client is None:
            import redis

            self._client = redis.from_url(self.redis_url, socket_connect_timeout=1, socket_timeout=1)
        return self._client

    def try_acquire(self) -> bool:
        try:
            r = self._conn()
            ok = r.set(_KEY, self.token, nx=True, ex=self.ttl_seconds)
            if ok:
                return True
            current = _token_str(r.get(_KEY))
            if current == self.token:
                r.expire(_KEY, self.ttl_seconds)
                return True
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("watch leader lock acquire failed: %s", exc)
            return False

    def renew(self) -> bool:
        try:
            r = self._conn()
            current = _token_str(r.get(_KEY))
            if current == self.token:
                r.expire(_KEY, self.ttl_seconds)
                return True
            return self.try_acquire()
        except Exception as exc:  # noqa: BLE001
            logger.warning("watch leader lock renew failed: %s", exc)
            return False

    def release(self) -> None:
        try:
            r = self._conn()
            current = _token_str(r.get(_KEY))
            if current == self.token:
                r.delete(_KEY)
        except Exception as exc:  # noqa: BLE001
            logger.warning("watch leader lock release failed: %s", exc)

    def ping(self) -> bool:
        try:
            return bool(self._conn().ping())
        except Exception:  # noqa: BLE001
            return False
