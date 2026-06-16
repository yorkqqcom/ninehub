"""Tushare SDK discovery and batch validation tests."""

import pytest

from app.services.tia.scan.tushare_sdk_discovery import (
    batch_validate_apis,
    inspect_tushare_sdk,
    merge_api_candidates,
    sdk_invalid_api_set,
    TushareSdkDiscoveryService,
)


def test_inspect_tushare_sdk() -> None:
    info = inspect_tushare_sdk()
    assert info.tushare_version
    assert info.access_model
    assert "daily" in info.pro_bar_hardcoded_apis


def test_merge_api_candidates_dedup() -> None:
    merged = merge_api_candidates(
        official_apis=["daily", "income"],
        local_apis=["income", "foo"],
        include_pro_bar=True,
    )
    assert "daily" in merged
    assert "income" in merged
    assert "foo" in merged
    assert merged == sorted(set(merged))


def test_batch_validate_apis_no_token() -> None:
    out = batch_validate_apis(None, ["daily", "income"])
    assert out["skipped"] is True
    assert out["reason"] == "no_token"
    assert out["unknown_count"] == 2


def test_batch_validate_apis_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_validate(token, api_name, params, max_calls_per_minute=None):
        valid = api_name not in {"pro", "broker_rec"}
        return {
            "api": api_name,
            "sdk_valid": valid,
            "sdk_validation_code": 0 if valid else 40101,
            "sdk_validation_msg": "ok" if valid else "invalid",
            "reason": "ok" if valid else "invalid_api_name",
        }

    monkeypatch.setattr(
        "app.services.tia.scan.tushare_sdk_discovery.validate_api_via_sdk",
        fake_validate,
    )
    out = batch_validate_apis("tok", ["daily", "pro", "income"], sleep_seconds=0)
    assert out["valid_count"] == 2
    assert out["invalid_count"] == 1
    assert "pro" in out["invalid_apis"]


def test_sdk_discovery_service_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.tia.scan.tushare_sdk_discovery.batch_validate_apis",
        lambda *a, **k: {
            "skipped": False,
            "validated_count": 1,
            "valid_count": 1,
            "invalid_count": 0,
            "unknown_count": 0,
            "valid_apis": ["daily"],
            "invalid_apis": [],
        },
    )
    report = TushareSdkDiscoveryService().run(
        official_apis=["daily"],
        token="tok",
        sleep_seconds=0,
    )
    assert report["package"]["tushare_version"]
    assert report["valid_count"] == 1


def test_sdk_invalid_api_set() -> None:
    assert sdk_invalid_api_set({"invalid_apis": ["pro"]}) == {"pro"}
    assert sdk_invalid_api_set(None) == set()
