"""Parse connect.cfg [HQHOST] for pytdx failover."""

from __future__ import annotations

from pathlib import Path


def first_host_from_connect_cfg(connect_cfg_path: str) -> tuple[str | None, int]:
    path = Path(connect_cfg_path)
    if not path.is_file():
        return None, 7709
    host: str | None = None
    port = 7709
    section = ""
    for line in path.read_text(encoding="gbk", errors="ignore").splitlines():
        text = line.strip()
        if text.startswith("[") and text.endswith("]"):
            section = text[1:-1].upper()
            continue
        if section != "HQHOST" or "=" not in text:
            continue
        key, val = text.split("=", 1)
        key = key.strip().upper()
        val = val.strip()
        if key == "IPAddress" and val:
            host = val
        elif key == "Port" and val.isdigit():
            port = int(val)
    return host, port
