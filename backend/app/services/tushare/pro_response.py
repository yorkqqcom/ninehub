"""Raw Tushare Pro API call + permission / min_points parsing (iteration-200 design).

Tushare SDK ``pro.query`` raises on ``code != 0`` and discards structured fields.
Scan probes need the full JSON body to read interface level and required points.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import requests

from app.services.collectors.tushare import wait_before_pro_call

_TUSHARE_DATAAPI_BASE = "http://api.waditu.com/dataapi"
_PERMISSION_ERROR_CODES = {-2002, 2002}
_PERMISSION_KEYWORDS = ("积分", "权限", "permission", "points", "访问该接口", "接口访问权限")

_LEVEL_DATA_KEYS = (
    "interface_level",
    "api_level",
    "level",
    "min_point",
    "min_points",
    "point_limit",
    "interface_point",
    "interface_points",
)

_API_PERMISSION_POINT_PATTERNS = (
    r"该接口需要至少(\d+)积分",
    r"该接口需要(\d+)积分",
    r"接口需要至少(\d+)积分",
    r"接口权限.*?(\d+)积分",
    r"需要至少(\d+)积分",
    r"至少(\d+)积分才可以",
    r"(\d+)积分权限",
    r"接口等级[：:\s]*(\d+)",
    r"接口等级为(\d+)",
    r"权限等级[：:\s]*(\d+)",
    r"(\d+)积分以上才可以调取",
    r"(\d+)积分以上可调取",
)


@dataclass
class ProApiResult:
    api_name: str
    ok: bool
    code: int | None = None
    msg: str = ""
    data: Any = None
    request_id: str | None = None
    df: pd.DataFrame | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_permission_error(self) -> bool:
        if self.code in _PERMISSION_ERROR_CODES:
            return True
        msg = self.msg or ""
        return any(k in msg for k in _PERMISSION_KEYWORDS)


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        pts = int(value)
    except (TypeError, ValueError):
        return None
    return pts if pts >= 0 else None


def _points_from_msg(msg: str) -> int | None:
    if not msg:
        return None
    for pattern in _API_PERMISSION_POINT_PATTERNS:
        match = re.search(pattern, msg)
        if match:
            return int(match.group(1))
    return None


def _points_from_data(data: Any) -> tuple[int | None, int | None]:
    """Return (min_points, interface_level) from structured ``data`` payload."""
    if not isinstance(data, dict):
        return None, None

    interface_level: int | None = None
    for key in ("interface_level", "api_level", "level"):
        interface_level = _parse_int(data.get(key))
        if interface_level is not None:
            break

    min_points: int | None = None
    for key in _LEVEL_DATA_KEYS:
        min_points = _parse_int(data.get(key))
        if min_points is not None:
            break

    if interface_level is None and min_points is not None:
        interface_level = min_points
    if min_points is None and interface_level is not None:
        min_points = interface_level
    return min_points, interface_level


def parse_permission_info(result: dict[str, Any] | ProApiResult) -> dict[str, Any]:
    """Extract min_points / interface_level from a Tushare Pro JSON response."""
    if isinstance(result, ProApiResult):
        code = result.code
        msg = result.msg
        data = result.data
    else:
        code = result.get("code")
        msg = str(result.get("msg") or "")
        data = result.get("data")

    is_perm = code in _PERMISSION_ERROR_CODES or any(k in msg for k in _PERMISSION_KEYWORDS)
    min_points, interface_level = _points_from_data(data)
    if min_points is None:
        min_points = _points_from_msg(msg)
    if interface_level is None and min_points is not None:
        interface_level = min_points

    source: str | None = None
    if min_points is not None or interface_level is not None:
        source = "api_live" if isinstance(data, dict) and any(data.get(k) is not None for k in _LEVEL_DATA_KEYS) else "api_live_msg"
    elif is_perm:
        source = "api_live_unknown"

    return {
        "is_permission_error": is_perm,
        "api_live_min_points": min_points,
        "interface_level": interface_level,
        "min_points_source": source,
        "api_error_code": code,
    }


def call_pro_api_raw(
    token: str,
    api_name: str,
    params: dict[str, Any],
    *,
    fields: str = "",
    max_calls_per_minute: int | None = None,
    timeout: int = 30,
) -> ProApiResult:
    """POST to Tushare dataapi and return the full parsed JSON envelope."""
    wait_before_pro_call(max_calls_per_minute)
    req_params = {
        "api_name": api_name,
        "token": token,
        "params": params,
        "fields": fields,
    }
    url = f"{_TUSHARE_DATAAPI_BASE}/{api_name}"
    response = requests.post(url, json=req_params, timeout=timeout)
    response.raise_for_status()
    payload: dict[str, Any] = json.loads(response.text)
    code = payload.get("code")
    try:
        code_int = int(code) if code is not None else None
    except (TypeError, ValueError):
        code_int = None

    df: pd.DataFrame | None = None
    if code_int == 0:
        data = payload.get("data") or {}
        columns = data.get("fields") or []
        items = data.get("items") or []
        df = pd.DataFrame(items, columns=columns) if columns else pd.DataFrame()

    return ProApiResult(
        api_name=api_name,
        ok=code_int == 0,
        code=code_int,
        msg=str(payload.get("msg") or ""),
        data=payload.get("data"),
        request_id=payload.get("request_id"),
        df=df,
        raw=payload,
    )
