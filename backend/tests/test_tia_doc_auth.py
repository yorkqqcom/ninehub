"""API tests for Tushare doc auth endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_doc_auth_get_and_put(client: AsyncClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.tia.tushare_doc_credential_service as mod

    cred_path = tmp_path / "tushare_doc_credentials.json"
    monkeypatch.setattr(mod, "_CREDENTIALS_PATH", cred_path)
    monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)

    get_res = await client.get("/api/v1/tia/doc-auth")
    assert get_res.status_code == 200
    assert get_res.json()["configured"] is False

    put_res = await client.put(
        "/api/v1/tia/doc-auth",
        json={"username": "13800000000", "password": "test-pass"},
    )
    assert put_res.status_code == 200
    body = put_res.json()
    assert body["configured"] is True
    assert body["username"] == "13800000000"
    assert body["has_password"] is True
    assert body["credential_source"] == "platform_file"


@pytest.mark.asyncio
async def test_doc_auth_verify_without_credentials(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.tia.tushare_doc_credential_service as mod

    monkeypatch.setattr(mod, "resolve_doc_credentials", lambda: (None, None))

    res = await client.post("/api/v1/tia/doc-auth/verify")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "未配置" in body["message"]
