"""Parse connect.cfg [HQHOST] and built-in HQ host failover list."""

from __future__ import annotations

import threading
from pathlib import Path

# Built-in HQ hosts as last resort (ordered by recent connectivity)
DEFAULT_HOSTS: list[tuple[str, int]] = [
    ("180.153.18.170", 7709),
    ("180.153.18.171", 7709),
    ("119.147.212.81", 7709),
    ("114.80.80.222", 7709),
    ("202.108.253.130", 7709),
    ("60.12.136.250", 7709),
]

_pref_lock = threading.Lock()
_preferred_host: tuple[str, int] | None = None


def remember_good_host(host: str, port: int) -> None:
    """Stick to last successful HQ host for faster subsequent connects."""
    global _preferred_host
    if not host:
        return
    with _pref_lock:
        _preferred_host = (host, int(port))


def first_host_from_connect_cfg(connect_cfg_path: str) -> tuple[str | None, int]:
    path = Path(connect_cfg_path)
    if not path.is_file():
        return None, 7709
    raw = path.read_bytes()
    text_body = None
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            text_body = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text_body is None:
        text_body = raw.decode("utf-8", errors="ignore")

    host: str | None = None
    port = 7709
    section = ""
    for line in text_body.splitlines():
        text = line.strip().lstrip("\ufeff")
        if not text or text.startswith(";") or text.startswith("#"):
            continue
        if text.startswith("[") and text.endswith("]"):
            section = text[1:-1].upper()
            continue
        if section != "HQHOST" or "=" not in text:
            continue
        key, val = text.split("=", 1)
        key = key.strip().upper()
        val = val.strip()
        if key in {"IPADDRESS", "IP", "HOSTNAME", "HOST"} and val:
            host = val
        elif key == "PORT" and val.isdigit():
            port = int(val)
    return host, port


def host_list(connect_cfg_path: str | None = None) -> list[tuple[str, int]]:
    """Preferred host (if any) + connect.cfg + DEFAULT_HOSTS (deduped)."""
    hosts: list[tuple[str, int]] = []
    with _pref_lock:
        preferred = _preferred_host
    if preferred:
        hosts.append(preferred)
    if connect_cfg_path:
        host, port = first_host_from_connect_cfg(connect_cfg_path)
        if host and (host, port) not in hosts:
            hosts.append((host, port))
    for h, p in DEFAULT_HOSTS:
        if (h, p) not in hosts:
            hosts.append((h, p))
    return hosts
