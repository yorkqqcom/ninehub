"""TIA preflight test service tests."""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.services.tia.preflight_test_service import (
    PREFLIGHT_CHECK_KEYS,
    TiaPreflightTestService,
    run_preflight_or_raise,
)
from app.core.exceptions import ValidationError


def test_preflight_has_eleven_checks() -> None:
    assert len(PREFLIGHT_CHECK_KEYS) == 11


def test_trade_cal_preflight_passes_without_live_probe() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    result = TiaPreflightTestService().run(session, "trade_cal", live_probe=False)
    session.close()
    assert result.api_name == "trade_cal"
    assert result.passed is True
    assert result.collect_pattern.get("mode") == "exchange_date_range"
    keys = {c.key for c in result.checks}
    assert keys == set(PREFLIGHT_CHECK_KEYS)
    budget = next(c for c in result.checks if c.key == "api_budget")
    assert budget.status == "pass"


def test_preflight_falls_back_to_wctapi_without_token() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    with patch(
        "app.services.tia.preflight_test_service.resolve_tushare_scan_credentials",
        return_value={"token": None, "account_points": 0},
    ):
        result = TiaPreflightTestService().run(session, "income", live_probe=True)
    session.close()
    assert result.passed is True
    live = next(c for c in result.checks if c.key == "live_probe")
    assert live.status == "warn"
    assert live.detail.get("fields_source") == "wctapi_md"
    assert len(result.actual_fields) > 0


def test_preflight_falls_back_to_wctapi_when_probe_empty() -> None:
    from app.services.tia.api_probe_service import ApiProbeResult

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    empty_probe = ApiProbeResult(
        api="income",
        status="failed_empty",
        message="接口返回空数据（可能为非交易日或参数无匹配）",
    )
    with patch(
        "app.services.tia.preflight_test_service.resolve_tushare_scan_credentials",
        return_value={"token": "fake-token", "account_points": 5000},
    ):
        with patch(
            "app.services.tia.preflight_test_service.TiaApiProbeService._probe_one",
            return_value=empty_probe,
        ):
            result = TiaPreflightTestService().run(session, "income", live_probe=True)
    session.close()
    assert result.passed is True
    live = next(c for c in result.checks if c.key == "live_probe")
    assert live.status == "warn"
    assert "wctapi" in live.message
    assert len(result.actual_fields) > 0


def test_preflight_fails_without_token_when_no_doc_fields() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    with patch(
        "app.services.tia.preflight_test_service.resolve_tushare_scan_credentials",
        return_value={"token": None, "account_points": 0},
    ):
        with patch(
            "app.services.tia.preflight_test_service._wctapi_output_fields",
            return_value=[],
        ):
            result = TiaPreflightTestService().run(session, "daily", live_probe=True)
    session.close()
    assert result.passed is False
    live = next(c for c in result.checks if c.key == "live_probe")
    assert live.status == "fail"


def test_trade_cal_api_budget_not_1663() -> None:
    result = TiaPreflightTestService().run(None, "trade_cal", live_probe=False)
    budget = next(c for c in result.checks if c.key == "api_budget")
    assert budget.detail.get("estimated", 999) <= 200
    assert budget.status == "pass"


def test_run_preflight_or_raise_blocks_on_failure() -> None:
    engine = create_engine("sqlite:///:memory:")
    session = sessionmaker(bind=engine)()

    with patch.object(TiaPreflightTestService, "run") as mock_run:
        mock_run.return_value = MagicMock(
            passed=False,
            blocking_errors=["simulated failure"],
        )
        with pytest.raises(ValidationError, match="Preflight"):
            run_preflight_or_raise(session, "daily")
    session.close()


@pytest.mark.asyncio
async def test_preflight_test_endpoint(client, db_session) -> None:
    from app.models.tia_proposal import TiaProposal

    proposal = TiaProposal(api_name="trade_cal", status="pending", action="review")
    db_session.add(proposal)
    await db_session.commit()

    response = await client.post(
        f"/api/v1/tia/proposals/{proposal.id}/preflight-test?live_probe=false"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["api_name"] == "trade_cal"
    assert body["passed"] is True
    assert len(body["checks"]) == 11

    refreshed = await db_session.get(TiaProposal, proposal.id)
    assert refreshed.activation_steps is not None
    assert refreshed.activation_steps["preflight_test"]["passed"] is True
