"""Process-wide quote cache with soft expiry."""

from __future__ import annotations

import threading
import time
from typing import Callable

from app.core.config import get_settings
from app.services.watch.types import QuoteBatch, QuoteSnap


class QuoteHub:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, QuoteSnap] = {}
        self._updated_at: float = 0.0
        self._last_ok_at: float | None = None
        self._last_error: str = ""
        self._active_host: str = ""
        self._config_epoch: int = 0
        self._provider_get: Callable[[list[str]], QuoteBatch] | None = None
        self._wanted: set[str] = set()

    def set_provider(self, fn: Callable[[list[str]], QuoteBatch]) -> None:
        self._provider_get = fn

    def bump_config_epoch(self) -> None:
        with self._lock:
            self._config_epoch += 1

    def invalidate_user(self, _user_id: int) -> None:
        self.bump_config_epoch()

    @property
    def config_epoch(self) -> int:
        return self._config_epoch

    def set_wanted_symbols(self, symbols: set[str]) -> None:
        with self._lock:
            self._wanted = set(symbols)
            self._prune_unlocked()

    def _prune_unlocked(self) -> None:
        """Drop cache entries outside the ticker wanted set."""
        if not self._wanted:
            self._items.clear()
            return
        self._items = {k: v for k, v in self._items.items() if k in self._wanted}

    def refresh(self, symbols: list[str] | None = None) -> QuoteBatch:
        settings = get_settings()
        hard_ttl = float(settings.watch_quote_hard_ttl_seconds)
        with self._lock:
            now = time.time()
            age = now - self._updated_at if self._updated_at else 9999.0
            target = list(symbols) if symbols is not None else sorted(self._wanted)
            if age < hard_ttl and self._items and symbols is None:
                return self._snapshot(stale=False, age=age)

        if not target or self._provider_get is None:
            with self._lock:
                age = time.time() - self._updated_at if self._updated_at else 9999.0
                return self._snapshot(stale=age >= hard_ttl, age=age)

        batch = self._provider_get(target)
        with self._lock:
            now = time.time()
            if batch.items:
                # Per-symbol merge: never overwrite a good frame with an unusable one
                any_fresh = False
                for sym, snap in batch.items.items():
                    good = (
                        snap.last_price is not None
                        and float(snap.last_price) > 0
                        and not snap.degraded
                    )
                    if good:
                        self._items[sym] = snap
                        any_fresh = True
                    elif sym not in self._items:
                        self._items[sym] = snap
                if any_fresh:
                    self._updated_at = now
                    if not batch.degraded:
                        self._last_ok_at = now
                        self._last_error = ""
                    else:
                        self._last_error = batch.message
                    self._active_host = batch.active_host
                    out = self._snapshot(stale=False, age=0.0)
                    out.degraded = batch.degraded
                    out.message = batch.message
                    out.active_host = self._active_host
                    return out
                # All returned snaps unusable: keep prior frames as soft-stale when possible
                if self._updated_at:
                    self._last_error = batch.message or "quotes unusable"
                    if batch.active_host:
                        self._active_host = batch.active_host
                    age = now - self._updated_at
                    out = self._snapshot(stale=True, age=age)
                    out.degraded = True
                    out.message = batch.message or self._last_error
                    out.active_host = self._active_host
                    return out
                self._updated_at = now
                self._last_error = batch.message
                self._active_host = batch.active_host
                out = self._snapshot(stale=False, age=0.0)
                out.degraded = True
                out.message = batch.message
                out.active_host = self._active_host
                return out

            # Pull failed: keep last snapshot, mark soft-stale for UI; alerts skip stale
            self._last_error = batch.message or "empty quotes"
            age = now - self._updated_at if self._updated_at else 9999.0
            out = self._snapshot(stale=True, age=age)
            out.degraded = True
            out.message = batch.message or self._last_error
            out.active_host = self._active_host
            return out

    def get_cached(self, symbols: list[str] | None = None) -> QuoteBatch:
        settings = get_settings()
        hard_ttl = float(settings.watch_quote_hard_ttl_seconds)
        with self._lock:
            now = time.time()
            age = now - self._updated_at if self._updated_at else 9999.0
            stale = age >= hard_ttl
            batch = self._snapshot(stale=stale, age=age)
            if symbols is not None:
                batch.items = {s: batch.items[s] for s in symbols if s in batch.items}
            return batch

    def get_or_refresh(self, symbols: list[str]) -> QuoteBatch:
        """HTTP/WS path: refresh when cache missing or soft-stale; return only requested symbols."""
        cached = self.get_cached(symbols)
        missing = [s for s in symbols if s not in cached.items]
        if missing or cached.stale:
            batch = self.refresh(symbols)
        else:
            batch = cached
        batch.items = {s: batch.items[s] for s in symbols if s in batch.items}
        return batch
    def status(self) -> dict:
        with self._lock:
            now = time.time()
            age = now - self._updated_at if self._updated_at else None
            return {
                "last_quote_ok_at": self._last_ok_at,
                "cache_age_seconds": age,
                "cache_stale": age is not None and age >= float(get_settings().watch_quote_hard_ttl_seconds),
                "last_error": self._last_error,
                "active_host": self._active_host,
                "symbol_count": len(self._items),
                "config_epoch": self._config_epoch,
            }

    def _snapshot(self, *, stale: bool, age: float) -> QuoteBatch:
        items: dict[str, QuoteSnap] = {}
        for sym, snap in self._items.items():
            items[sym] = QuoteSnap(
                symbol=snap.symbol,
                last_price=snap.last_price,
                open=snap.open,
                pre_close=snap.pre_close,
                high=snap.high,
                low=snap.low,
                volume=snap.volume,
                amount=snap.amount,
                change_pct=snap.change_pct,
                ts_ms=snap.ts_ms,
                degraded=snap.degraded,
                stale=stale,
                age_seconds=age,
                name=snap.name,
            )
        return QuoteBatch(items=items, stale=stale)


_hub: QuoteHub | None = None
_hub_lock = threading.Lock()


def get_quote_hub() -> QuoteHub:
    global _hub
    with _hub_lock:
        if _hub is None:
            _hub = QuoteHub()
        return _hub
