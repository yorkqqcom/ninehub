"""In-memory rolling windows for velocity / volume_ratio (delta volume)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class SymbolWindow:
    prices: deque[tuple[int, float]] = field(default_factory=lambda: deque(maxlen=120))
    volumes: deque[tuple[int, float]] = field(default_factory=lambda: deque(maxlen=120))
    trade_date: str = ""

    def push(self, *, ts_ms: int, last_price: float, volume: float | None, trade_date: str) -> None:
        if trade_date and trade_date != self.trade_date:
            self.prices.clear()
            self.volumes.clear()
            self.trade_date = trade_date
        if last_price > 0:
            self.prices.append((ts_ms, last_price))
        if volume is not None and volume >= 0:
            self.volumes.append((ts_ms, float(volume)))

    def price_velocity(self, window_seconds: int, now_ms: int, *, min_samples: int = 3) -> float | None:
        cutoff = now_ms - window_seconds * 1000
        pts = [(t, p) for t, p in self.prices if t >= cutoff]
        if len(pts) < min_samples:
            return None
        t0, p0 = pts[0]
        t1, p1 = pts[-1]
        dt = (t1 - t0) / 1000.0
        if dt <= 0 or p0 <= 0:
            return None
        return ((p1 - p0) / p0) / dt

    def volume_ratio_delta(self, window_seconds: int, now_ms: int, *, min_samples: int = 3) -> float | None:
        """Ratio of latest Δvol to mean of prior Δvols in window."""
        cutoff = now_ms - window_seconds * 1000
        pts = [(t, v) for t, v in self.volumes if t >= cutoff]
        if len(pts) < min_samples + 1:
            return None
        deltas: list[float] = []
        for i in range(1, len(pts)):
            d = pts[i][1] - pts[i - 1][1]
            if d < 0:
                d = 0.0
            deltas.append(d)
        if len(deltas) < min_samples:
            return None
        current = deltas[-1]
        prior = deltas[:-1]
        avg = sum(prior) / len(prior) if prior else 0.0
        if avg <= 0:
            return None
        return current / avg


class WindowStore:
    def __init__(self) -> None:
        self._by_symbol: dict[str, SymbolWindow] = {}

    def get(self, symbol: str) -> SymbolWindow:
        if symbol not in self._by_symbol:
            self._by_symbol[symbol] = SymbolWindow()
        return self._by_symbol[symbol]

    def retain(self, symbols: set[str]) -> None:
        """Drop windows for symbols no longer watched."""
        for sym in list(self._by_symbol.keys()):
            if sym not in symbols:
                del self._by_symbol[sym]

    def clear_all(self) -> None:
        self._by_symbol.clear()
