"""WebSocket auth helpers (no DB imports)."""

from __future__ import annotations

from typing import Any


def token_from_ws_protocols(headers: Any) -> str:
    """Prefer Sec-WebSocket-Protocol: bearer.<jwt> (avoids query-string access logs)."""
    get = getattr(headers, "get", None)
    if callable(get):
        proto = (get("sec-websocket-protocol") or "").strip()
    elif isinstance(headers, dict):
        proto = (headers.get("sec-websocket-protocol") or "").strip()
    else:
        proto = ""
    if not proto:
        return ""
    for part in proto.split(","):
        p = part.strip()
        if p.lower().startswith("bearer."):
            return p[7:].strip()
        if p.lower().startswith("access_token."):
            return p[len("access_token.") :].strip()
    return ""
