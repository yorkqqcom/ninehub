"""Tests for trading calendar nearest day helper."""

from datetime import date

from app.services.trading_calendar.service import TradingCalendarService


def test_nearest_trading_day_weekend() -> None:
    cal = TradingCalendarService()
    d, adjusted = cal.nearest_trading_day_on_or_before(date(2024, 11, 23))
    assert adjusted is True
    assert d < date(2024, 11, 23)
    assert cal.is_trading_day(d)[0] is True


def test_nearest_trading_day_already_trading() -> None:
    cal = TradingCalendarService()
    d, adjusted = cal.nearest_trading_day_on_or_before(date(2024, 11, 20))
    assert adjusted is False
    assert d == date(2024, 11, 20)
