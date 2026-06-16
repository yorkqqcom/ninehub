"""TIA scan API probe unit tests."""

import pandas as pd
import pytest

from app.services.tia.api_probe_service import TiaApiProbeService
from app.services.tushare.pro_response import ProApiResult

def _mock_raw_caller(responses: dict[str, ProApiResult | Exception]):
    from app.services.tushare.pro_response import ProApiResult

    def caller(
        token: str,
        api_name: str,
        params: dict,
        max_calls_per_minute: int | None,
    ) -> ProApiResult:
        assert token == "test-token"
        resp = responses.get(api_name)
        if isinstance(resp, Exception):
            raise resp
        return resp if resp is not None else ProApiResult(api_name=api_name, ok=True, code=0, df=pd.DataFrame())

    return caller


def _mock_caller(responses: dict[str, pd.DataFrame | Exception]):
    def caller(token: str, api_name: str, params: dict) -> pd.DataFrame:
        assert token == "test-token"
        resp = responses.get(api_name)
        if isinstance(resp, Exception):
            raise resp
        return resp if resp is not None else pd.DataFrame()

    return caller


def test_probe_strips_fields_param_for_full_output() -> None:
    captured: dict[str, dict] = {}

    def caller(token: str, api_name: str, params: dict) -> pd.DataFrame:
        captured[api_name] = params
        return pd.DataFrame(
            {
                "trade_date": ["20240102"],
                "ts_code": ["000001.SZ"],
                "exalter": ["x"],
                "buy": [1.0],
                "sell": [0.0],
                "net_buy": [1.0],
            }
        )

    svc = TiaApiProbeService(caller=caller)
    result = svc.probe_catalog_apis(["top_inst"], token="test-token", account_points=5000)[0]
    assert result["status"] == "ok"
    assert "fields" not in captured["top_inst"]
    assert "net_buy" in result["actual_fields"]


def test_probe_ok_when_fields_match() -> None:
    svc = TiaApiProbeService(
        caller=_mock_caller(
            {
                "daily": pd.DataFrame(
                    {
                        "ts_code": ["000001.SZ"],
                        "trade_date": ["20240102"],
                        "open": [10.0],
                        "high": [10.5],
                        "low": [9.8],
                        "close": [10.2],
                        "pre_close": [10.0],
                        "change": [0.2],
                        "pct_chg": [2.0],
                        "vol": [1000],
                        "amount": [10200.0],
                    }
                )
            }
        )
    )
    result = svc.probe_catalog_apis(["daily"], token="test-token", account_points=5000)[0]
    assert result["status"] == "ok"
    assert result["doc_consistent"] is True
    assert result["rows"] == 1
    assert result["missing_fields"] == []


def test_probe_doc_field_mismatch_still_ok_with_partial_return() -> None:
    svc = TiaApiProbeService(
        caller=_mock_caller(
            {
                "daily": pd.DataFrame(
                    {
                        "ts_code": ["000001.SZ"],
                        "trade_date": ["20240102"],
                        "open": [10.0],
                    }
                )
            }
        )
    )
    result = svc.probe_catalog_apis(["daily"], token="test-token", account_points=5000)[0]
    assert result["status"] == "ok"
    assert "high" in result["missing_fields"]
    assert result["doc_consistent"] is False


def test_probe_skipped_no_token() -> None:
    svc = TiaApiProbeService(caller=_mock_caller({}))
    result = svc.probe_catalog_apis(["daily"], token=None, account_points=5000)[0]
    assert result["status"] == "skipped_no_token"


def test_probe_skipped_insufficient_points_calls_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.tushare.pro_response import ProApiResult

    monkeypatch.setattr(
        "app.services.tia.api_probe_service._local_catalog_min_points",
        lambda api_name: 600 if api_name == "income" else 120,
    )
    svc = TiaApiProbeService(
        raw_caller=_mock_raw_caller(
            {
                "income": ProApiResult(
                    api_name="income",
                    ok=False,
                    code=-2002,
                    msg="抱歉，您没有接口访问权限，该接口需要至少2000积分才可以调取",
                )
            }
        )
    )
    result = svc.probe_catalog_apis(["income"], token="test-token", account_points=100)[0]
    assert result["status"] == "failed_points"
    assert result["api_live_min_points"] == 2000
    assert result["interface_level"] == 2000
    assert "2000" in result["message"]


def test_probe_failed_empty() -> None:
    svc = TiaApiProbeService(caller=_mock_caller({"daily": pd.DataFrame()}))
    result = svc.probe_catalog_apis(["daily"], token="test-token", account_points=5000)[0]
    assert result["status"] == "failed_empty"


def test_probe_failed_api_error() -> None:
    svc = TiaApiProbeService(
        caller=_mock_caller({"daily": RuntimeError("network timeout")})
    )
    result = svc.probe_catalog_apis(["daily"], token="test-token", account_points=5000)[0]
    assert result["status"] == "failed"
    assert "network timeout" in result["message"]


def test_probe_failed_points_error() -> None:
    svc = TiaApiProbeService(
        caller=_mock_caller({"daily": RuntimeError("积分不足，无法访问")})
    )
    result = svc.probe_catalog_apis(["daily"], token="test-token", account_points=5000)[0]
    assert result["status"] == "failed_points"


def test_probe_failed_points_parses_required_points() -> None:
    svc = TiaApiProbeService(
        raw_caller=_mock_raw_caller(
            {
                "daily": ProApiResult(
                    api_name="daily",
                    ok=False,
                    code=-2002,
                    msg="该接口需要至少5000积分才可以调取",
                    data={"interface_level": 5000},
                )
            }
        )
    )
    result = svc.probe_catalog_apis(["daily"], token="test-token", account_points=120)[0]
    assert result["status"] == "failed_points"
    assert result["api_live_min_points"] == 5000
    assert result["interface_level"] == 5000
    assert result["min_points_source"] == "api_live"


def test_probe_on_progress_callback() -> None:
    events: list[tuple[str, int, int]] = []

    def caller(token: str, api_name: str, params: dict) -> pd.DataFrame:
        return pd.DataFrame({"ts_code": ["x"], "trade_date": ["20240102"], "open": [1], "high": [1], "low": [1], "close": [1], "vol": [1]})

    def on_progress(api: str, row: dict, idx: int, total: int) -> None:
        events.append((api, idx, total))

    svc = TiaApiProbeService(caller=caller)
    svc.probe_catalog_apis(
        ["daily", "stock_basic"],
        token="test-token",
        account_points=5000,
        on_progress=on_progress,
    )
    assert len(events) == 2
    assert events[0][1] == 1
    assert events[1][2] == 2


def test_probe_resolves_dynamic_trade_date() -> None:
    captured: dict[str, dict] = {}

    def caller(token: str, api_name: str, params: dict) -> pd.DataFrame:
        captured[api_name] = params
        return pd.DataFrame(
            {
                "trade_date": [params.get("trade_date", "")],
                "ts_code": ["000001.SZ"],
                "exalter": ["x"],
                "buy": [1.0],
                "sell": [0.0],
            }
        )

    svc = TiaApiProbeService(caller=caller)
    result = svc.probe_catalog_apis(["top_inst"], token="test-token", account_points=5000)[0]
    assert result["status"] == "ok"
    assert captured["top_inst"]["trade_date"].isdigit()
    assert len(captured["top_inst"]["trade_date"]) == 8


def test_probe_summarize() -> None:
    probes = [
        {"status": "ok"},
        {"status": "doc_field_mismatch", "points_doc_mismatch": True},
        {"status": "failed"},
        {"status": "skipped_no_token"},
    ]
    summary = TiaApiProbeService.summarize(probes)
    assert summary["ok"] == 1
    assert summary["doc_field_mismatch"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert summary["points_doc_mismatch"] == 1


def test_probe_points_doc_mismatch_when_local_catalog_differs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.tia.scan.types import OfficialApiEntry

    monkeypatch.setattr(
        "app.services.tia.api_probe_service._local_catalog_min_points",
        lambda api_name: 120,
    )
    monkeypatch.setattr(
        "app.services.tia.api_probe_service.resolve_min_points_for_doc_id",
        lambda doc_id, **kwargs: (600, "doc_page_parsed"),
    )

    svc = TiaApiProbeService(caller=_mock_caller({}))
    result = svc.probe_catalog_apis(
        ["income"],
        token=None,
        account_points=5000,
        official_map={
            "income": OfficialApiEntry(
                api="income",
                doc_id=33,
                min_points=600,
            )
        },
    )[0]
    assert result["catalog_min_points"] == 120
    assert result["official_doc_min_points"] == 600
    assert result["points_doc_mismatch"] is True


def test_probe_uses_override_min_points_for_live_call() -> None:
    from app.services.tushare.pro_response import ProApiResult

    svc = TiaApiProbeService(
        raw_caller=_mock_raw_caller(
            {
                "daily": ProApiResult(
                    api_name="daily",
                    ok=False,
                    code=-2002,
                    msg="该接口需要至少5000积分才可以调取",
                )
            }
        )
    )
    result = svc.probe_catalog_apis(
        ["daily"],
        token="test-token",
        account_points=2000,
        override_points={"daily": 5000},
    )[0]
    assert result["status"] == "failed_points"
    assert result["catalog_min_points"] == 5000
    assert result["api_live_min_points"] == 5000


def test_probe_override_points_doc_mismatch_vs_official() -> None:
    from app.services.tia.scan.types import OfficialApiEntry

    svc = TiaApiProbeService(caller=_mock_caller({}))
    result = svc.probe_catalog_apis(
        ["daily"],
        token=None,
        account_points=5000,
        override_points={"daily": 5000},
        official_map={
            "daily": OfficialApiEntry(api="daily", doc_id=27, min_points=120),
        },
    )[0]
    assert result["catalog_min_points"] == 5000
    assert result["official_doc_min_points"] == 120
    assert result["points_doc_mismatch"] is True
