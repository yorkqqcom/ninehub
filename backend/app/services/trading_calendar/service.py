"""A-share trading calendar — shared by gate nodes and Beat dispatch (D-06)."""

from __future__ import annotations

from datetime import date

# 2025–2026 法定节假日（上交所休市，精简集）
CN_HOLIDAYS: frozenset[date] = frozenset(
    {
        date(2025, 1, 1),
        date(2025, 1, 28),
        date(2025, 1, 29),
        date(2025, 1, 30),
        date(2025, 1, 31),
        date(2025, 2, 1),
        date(2025, 2, 2),
        date(2025, 2, 3),
        date(2025, 2, 4),
        date(2025, 4, 4),
        date(2025, 4, 5),
        date(2025, 4, 6),
        date(2025, 5, 1),
        date(2025, 5, 2),
        date(2025, 5, 3),
        date(2025, 5, 4),
        date(2025, 5, 5),
        date(2025, 5, 31),
        date(2025, 6, 1),
        date(2025, 6, 2),
        date(2025, 10, 1),
        date(2025, 10, 2),
        date(2025, 10, 3),
        date(2025, 10, 4),
        date(2025, 10, 5),
        date(2025, 10, 6),
        date(2025, 10, 7),
        date(2025, 10, 8),
        date(2026, 1, 1),
        date(2026, 1, 2),
        date(2026, 1, 3),
    }
)


class TradingCalendarService:
    def is_trading_day(self, day: date | None = None) -> tuple[bool, str]:
        target = day or date.today()
        if target.weekday() >= 5:
            return False, f"{target.isoformat()} 非交易日（周末）"
        if target in CN_HOLIDAYS:
            return False, f"{target.isoformat()} 非交易日（法定节假日）"
        return True, f"{target.isoformat()} A股交易日"

    def nearest_trading_day_on_or_before(self, day: date) -> tuple[date, bool]:
        """Return the nearest A-share trading day on or before ``day``."""
        cursor = day
        for _ in range(366):
            ok, _ = self.is_trading_day(cursor)
            if ok:
                return cursor, cursor != day
            cursor = date.fromordinal(cursor.toordinal() - 1)
        raise ValueError(f"no trading day found on or before {day.isoformat()}")


def is_trading_day(day: date | None = None) -> tuple[bool, str]:
    """Module-level helper for gate nodes."""
    return TradingCalendarService().is_trading_day(day)
