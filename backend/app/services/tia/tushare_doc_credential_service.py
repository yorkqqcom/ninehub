"""Persist and resolve Tushare document/2 login credentials (admin UI + .env fallback)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_CREDENTIALS_PATH = _DATA_DIR / "tushare_doc_credentials.json"


def credentials_file_path() -> Path:
    return _CREDENTIALS_PATH


def load_stored_credentials() -> dict[str, str]:
    if not _CREDENTIALS_PATH.is_file():
        return {}
    try:
        raw = json.loads(_CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    username = raw.get("username")
    password = raw.get("password")
    if username:
        out["username"] = str(username).strip()
    if password:
        out["password"] = str(password)
    return out


def resolve_doc_credentials() -> tuple[str | None, str | None]:
    """UI/file credentials override env when both username and password are set."""
    stored = load_stored_credentials()
    if stored.get("username") and stored.get("password"):
        return stored["username"], stored["password"]
    settings = get_settings()
    username = (settings.tushare_doc_username or "").strip() or None
    password = settings.tushare_doc_password or None
    return username, password


def credential_source() -> str:
    stored = load_stored_credentials()
    if stored.get("username") and stored.get("password"):
        return "platform_file"
    settings = get_settings()
    if settings.tushare_doc_username and settings.tushare_doc_password:
        return "env"
    return "none"


def save_doc_credentials(username: str, password: str) -> None:
    username = username.strip()
    if not username:
        raise ValueError("用户名不能为空")
    if not password:
        raise ValueError("密码不能为空")
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"username": username, "password": password}
    _CREDENTIALS_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def clear_doc_credentials() -> None:
    if _CREDENTIALS_PATH.is_file():
        _CREDENTIALS_PATH.unlink()


def get_doc_auth_status() -> dict[str, Any]:
    from app.services.tia.scan.tushare_doc_auth import resolve_storage_path, storage_state_exists

    username, password = resolve_doc_credentials()
    return {
        "configured": bool(username and password),
        "username": username,
        "has_password": bool(password),
        "credential_source": credential_source(),
        "storage_state_exists": storage_state_exists(),
        "storage_path": str(resolve_storage_path()),
        "credentials_path": str(_CREDENTIALS_PATH),
    }


def verify_doc_login(*, headless: bool = True) -> dict[str, Any]:
    """Login to tushare.pro/document/2 and persist Playwright storage state."""
    from app.services.tia.scan.tushare_doc_auth import (
        TushareDocAuthSession,
        resolve_storage_path,
        storage_state_exists,
    )

    username, password = resolve_doc_credentials()
    if not username or not password:
        return {
            "ok": False,
            "message": "未配置文档站账号：请在 TIA 设置或 .env 中填写 TUSHARE_DOC_USERNAME/PASSWORD",
            "storage_state_exists": storage_state_exists(),
        }
    try:
        with TushareDocAuthSession(headless=headless, login_if_needed=True) as auth:
            html = auth.fetch_page_html(26, timeout_ms=30000)
        plain_len = len(html or "")
        ok = plain_len > 500 and ("接口" in html or "trade_cal" in html.lower())
        return {
            "ok": ok,
            "message": "登录成功，已保存文档站会话" if ok else "登录后会话无效，请检查账号密码",
            "storage_state_exists": storage_state_exists(),
            "storage_path": str(resolve_storage_path()),
            "preview_bytes": plain_len,
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": str(exc),
            "storage_state_exists": storage_state_exists(),
            "storage_path": str(resolve_storage_path()),
        }
