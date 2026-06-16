"""TIA scan probe registry: explicit probes for APIs without template coverage."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from app.services.trading_calendar.service import CN_HOLIDAYS
from app.services.tia.scan.tushare_doc_registry import resolve_api_meta

# Explicit probe specs not covered by category templates alone.
OFFICIAL_ONLY_API_PROBES: dict[str, dict[str, Any]] = {
    "balancesheet": {
        "min_points": 600,
        "doc_id": 36,
        "probe": {
            "params": {
                "ts_code": "000001.SZ",
                "period": "20231231",
                "fields": "ts_code,end_date,total_assets,total_liab",
            },
            "expected_fields": ["ts_code", "end_date", "total_assets"],
        },
    },
}


def api_probe_meta(api_name: str) -> dict[str, Any] | None:
    explicit = OFFICIAL_ONLY_API_PROBES.get(api_name)
    if explicit:
        return explicit
    return resolve_api_meta(api_name)


def probeable_api_names(local_apis: list[str], new_on_official: list[str]) -> list[str]:
    candidates = set(local_apis) | set(new_on_official)
    return sorted(
        api
        for api in candidates
        if api_probe_meta(api) and (api_probe_meta(api) or {}).get("probe")
    )


def last_trading_day(ref: date | None = None, lookback: int = 15) -> date:
    """Walk backward to the most recent A-share trading day."""
    day = ref or date.today()
    for _ in range(lookback):
        if day.weekday() < 5 and day not in CN_HOLIDAYS:
            return day
        day -= timedelta(days=1)
    return ref or date.today()


def resolve_probe_params(raw_params: dict[str, Any]) -> dict[str, Any]:
    """Expand dynamic placeholders in probe call params."""
    params = dict(raw_params)
    for key, value in list(params.items()):
        if value == "__LAST_TRADING_DAY__":
            params[key] = last_trading_day().strftime("%Y%m%d")
        elif value == "__LAST_TRADING_WEEK__":
            end = last_trading_day()
            start = end
            for _ in range(7):
                start -= timedelta(days=1)
                if start.weekday() < 5 and start not in CN_HOLIDAYS:
                    break
            if key == "start_date":
                params[key] = start.strftime("%Y%m%d")
            elif key == "end_date":
                params[key] = end.strftime("%Y%m%d")
    return params
