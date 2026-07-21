"""Small TTL+LRU cache without external deps."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Generic, TypeVar

T = TypeVar("T")


class TtlLruCache(Generic[T]):
    def __init__(self, maxsize: int = 128, ttl: float = 15.0) -> None:
        self.maxsize = max(1, int(maxsize))
        self.ttl = float(ttl)
        self._data: OrderedDict[str, tuple[float, T]] = OrderedDict()

    def get(self, key: str) -> T | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.time() >= expires_at:
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value: T) -> None:
        self._data[key] = (time.time() + self.ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)
