"""ApiSpecSyncService integration tests (wctapi + SDK mock)."""

import httpx
import pytest
import respx

from app.services.tia.scan.api_spec_sync_service import ApiSpecSyncService
from app.services.tia.scan.api_spec_store import load_api_specs_cache

DAILY_MD = """
## A股日线行情
----
接口：daily
描述：获取股票行情数据

**输入参数**

名称 | 类型 | 必选 | 描述
---- | ----- | ---- | ----
ts_code | str | N | 股票代码

**输出参数**

名称 | 类型 | 描述
--- | ---- | ----
ts_code | str | 股票代码 |
open | float | 开盘价 |
"""


@respx.mock
def test_api_spec_sync_writes_cache(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.tia.scan import api_spec_store

    cache_file = tmp_path / "specs.json"
    monkeypatch.setattr(api_spec_store, "_SPECS_CACHE_PATH", cache_file)

    respx.get("https://tushare.pro/wctapi/documents/27.md").mock(
        return_value=httpx.Response(200, text=DAILY_MD)
    )

    def fake_validate(token, api_name, params, max_calls_per_minute=None):
        return {
            "api": api_name,
            "sdk_valid": True,
            "sdk_validation_code": 0,
            "sdk_validation_msg": "ok",
            "reason": "ok",
        }

    monkeypatch.setattr(
        "app.services.tia.scan.api_spec_sync_service.validate_api_via_sdk",
        fake_validate,
    )

    result = ApiSpecSyncService().run(
        [27],
        token="test-token",
        validate_sdk=True,
        write_cache=True,
        sleep_seconds=0,
    )
    assert result["synced_count"] == 1
    cache = load_api_specs_cache()
    row = cache.get("27")
    assert row is not None
    assert row["api"] == "daily"
    assert row.get("probe_spec", {}).get("params")
    assert "open" in (row.get("output_fields") or [])


@respx.mock
def test_api_spec_sync_skips_sdk_invalid_apis(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.tia.scan import api_spec_store

    cache_file = tmp_path / "specs.json"
    monkeypatch.setattr(api_spec_store, "_SPECS_CACHE_PATH", cache_file)

    respx.get("https://tushare.pro/wctapi/documents/27.md").mock(
        return_value=httpx.Response(200, text=DAILY_MD)
    )

    result = ApiSpecSyncService().run(
        [27],
        token=None,
        validate_sdk=False,
        write_cache=True,
        sleep_seconds=0,
        skip_apis={"daily"},
    )
    assert result["synced_count"] == 0
    assert result["skipped_sdk_invalid_count"] == 1
    assert "daily" in result["skipped_sdk_invalid_apis"]
