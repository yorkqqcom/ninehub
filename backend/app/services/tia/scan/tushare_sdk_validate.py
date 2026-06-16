"""Validate Tushare API names via live pro_api call (SDK/server ground truth)."""

from __future__ import annotations

from typing import Any

from app.services.tushare.pro_response import call_pro_api_raw

_INVALID_API_CODES = {40101}
# 50101 missing required params → API exists
_EXISTS_HINT_CODES = {0, -2002, 2002, 40203, 50101}


def validate_api_via_sdk(
    token: str,
    api_name: str,
    params: dict[str, Any] | None = None,
    *,
    max_calls_per_minute: int | None = None,
) -> dict[str, Any]:
    """Return whether api_name is recognized by Tushare dataapi."""
    if not token:
        return {
            "api": api_name,
            "sdk_valid": None,
            "reason": "no_token",
        }

    result = call_pro_api_raw(
        token,
        api_name,
        params or {},
        max_calls_per_minute=max_calls_per_minute,
    )
    code = result.code
    msg = result.msg or ""

    if code in _INVALID_API_CODES or "请指定正确的接口名" in msg:
        sdk_valid = False
        reason = "invalid_api_name"
    elif code in _EXISTS_HINT_CODES or result.ok:
        sdk_valid = True
        reason = "ok" if result.ok else "exists_with_error"
    else:
        sdk_valid = True
        reason = "unknown_code_assume_exists"

    return {
        "api": api_name,
        "sdk_valid": sdk_valid,
        "sdk_validation_code": code,
        "sdk_validation_msg": msg[:300],
        "reason": reason,
    }


def list_pro_bar_apis() -> list[str]:
    """API names hard-referenced by tushare.pro_bar / pro_bar_vip source."""
    import inspect
    import re

    import tushare as ts

    apis: set[str] = set()
    for fn_name in ("pro_bar", "pro_bar_vip"):
        fn = getattr(ts, fn_name, None)
        if fn is None:
            continue
        apis.update(re.findall(r"api\.([a-z][a-z0-9_]*)\(", inspect.getsource(fn)))
    return sorted({a.replace("_vip", "") for a in apis if not a.endswith("_vip")} | apis)
