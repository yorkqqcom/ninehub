"""Tests for Tushare document/2 credential storage."""

from pathlib import Path

import pytest

from app.services.tia.tushare_doc_credential_service import (
    clear_doc_credentials,
    credential_source,
    load_stored_credentials,
    resolve_doc_credentials,
    save_doc_credentials,
)


def test_save_and_resolve_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.tia.tushare_doc_credential_service as mod

    cred_path = tmp_path / "tushare_doc_credentials.json"
    monkeypatch.setattr(mod, "_CREDENTIALS_PATH", cred_path)
    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)

    save_doc_credentials("user@example.com", "secret-pass")
    assert load_stored_credentials() == {
        "username": "user@example.com",
        "password": "secret-pass",
    }
    assert resolve_doc_credentials() == ("user@example.com", "secret-pass")
    assert credential_source() == "platform_file"

    clear_doc_credentials()
    assert not cred_path.is_file()


def test_env_fallback_when_no_file(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.tia.tushare_doc_credential_service as mod
    from app.core.config import get_settings

    monkeypatch.setattr(mod, "_CREDENTIALS_PATH", Path("/nonexistent/creds.json"))
    get_settings.cache_clear()
    monkeypatch.setenv("TUSHARE_DOC_USERNAME", "env_user")
    monkeypatch.setenv("TUSHARE_DOC_PASSWORD", "env_pass")
    get_settings.cache_clear()

    assert resolve_doc_credentials() == ("env_user", "env_pass")
    assert credential_source() == "env"
    get_settings.cache_clear()
