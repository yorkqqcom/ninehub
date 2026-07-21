"""Trading-hours gate for WatchTicker (Asia/Shanghai)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings
from app.services.trading_calendar.service import TradingCalendarService

_TZ = ZoneInfo("Asia/Shanghai")


def _parse_hhmm(text: str) -> int:
    h, m = text.split(":", 1)
    return int(h) * 60 + int(m)


def session_trade_date() -> str:
    return datetime.now(_TZ).date().isoformat()


def is_watch_session_open(now: datetime | None = None) -> tuple[bool, str]:
    settings = get_settings()
    now = now or datetime.now(_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=_TZ)
    else:
        now = now.astimezone(_TZ)

    cal = TradingCalendarService()
    ok, reason = cal.is_trading_day(now.date())
    if not ok:
        return False, reason

    minutes = now.hour * 60 + now.minute
    m0 = _parse_hhmm(settings.watch_session_morning_start)
    m1 = _parse_hhmm(settings.watch_session_morning_end)
    a0 = _parse_hhmm(settings.watch_session_afternoon_start)
    a1 = _parse_hhmm(settings.watch_session_afternoon_end)
    if m0 <= minutes <= m1 or a0 <= minutes <= a1:
        return True, "in_session"
    return False, "off_hours"
