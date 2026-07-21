"""Watch package."""

from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["get_quote_hub", "get_watch_ticker"]


def get_quote_hub():
    from app.services.watch.hub import get_quote_hub as _get

    return _get()


def get_watch_ticker():
    from app.services.watch.ticker import get_watch_ticker as _get

    return _get()


if TYPE_CHECKING:
    from app.services.watch.hub import QuoteHub
    from app.services.watch.ticker import WatchTicker
