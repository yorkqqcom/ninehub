"""Tushare SDK API name validation tests."""

import pytest

from app.services.tia.scan.tushare_sdk_validate import list_pro_bar_apis, validate_api_via_sdk


def test_validate_invalid_api_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.tushare.pro_response import ProApiResult

    def fake_call(token, api_name, params, max_calls_per_minute=None):
        return ProApiResult(
            api_name=api_name,
            ok=False,
            code=40101,
            msg="请指定正确的接口名",
        )

    monkeypatch.setattr(
        "app.services.tia.scan.tushare_sdk_validate.call_pro_api_raw",
        fake_call,
    )
    out = validate_api_via_sdk("tok", "pro")
    assert out["sdk_valid"] is False
    assert out["sdk_validation_code"] == 40101


def test_validate_exists_missing_params(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.tushare.pro_response import ProApiResult

    def fake_call(token, api_name, params, max_calls_per_minute=None):
        return ProApiResult(
            api_name=api_name,
            ok=False,
            code=50101,
            msg="必填参数, ts_code",
        )

    monkeypatch.setattr(
        "app.services.tia.scan.tushare_sdk_validate.call_pro_api_raw",
        fake_call,
    )
    out = validate_api_via_sdk("tok", "daily", {})
    assert out["sdk_valid"] is True


def test_list_pro_bar_apis_non_empty() -> None:
    apis = list_pro_bar_apis()
    assert "daily" in apis
