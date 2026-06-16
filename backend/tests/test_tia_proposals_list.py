"""Tests for TIA proposal list enhancements."""

import pytest
from httpx import AsyncClient

from app.models.tia_proposal import TiaProposal


@pytest.mark.asyncio
async def test_list_proposals_includes_summary_and_enrichment(client: AsyncClient, db_session) -> None:
    db_session.add(
        TiaProposal(
            api_name="income",
            status="pending",
            reason="new_on_official",
            data_type="tia_income",
        )
    )
    db_session.add(
        TiaProposal(api_name="daily", status="approved", data_type="tia_daily")
    )
    await db_session.commit()

    response = await client.get("/api/v1/tia/proposals?limit=10")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    assert body["summary"]["pending"] >= 1
    assert body["summary"]["approved"] >= 1
    income = next(i for i in body["items"] if i["api_name"] == "income")
    assert income["doc_id"] == 33
    assert income["min_points"] == 2000
    assert "doc_id=33" in (income.get("doc_url") or "")


@pytest.mark.asyncio
async def test_list_proposals_filter_status(client: AsyncClient, db_session) -> None:
    db_session.add(TiaProposal(api_name="foo_api", status="pending"))
    db_session.add(TiaProposal(api_name="bar_api", status="rejected"))
    await db_session.commit()

    response = await client.get("/api/v1/tia/proposals?status=pending")
    assert response.status_code == 200
    items = response.json()["items"]
    assert all(i["status"] == "pending" for i in items)
    assert any(i["api_name"] == "foo_api" for i in items)


@pytest.mark.asyncio
async def test_list_proposals_search_q(client: AsyncClient, db_session) -> None:
    db_session.add(TiaProposal(api_name="cyq_perf", status="pending"))
    db_session.add(TiaProposal(api_name="daily", status="pending"))
    await db_session.commit()

    response = await client.get("/api/v1/tia/proposals?q=cyq")
    assert response.status_code == 200
    names = [i["api_name"] for i in response.json()["items"]]
    assert "cyq_perf" in names
    assert "daily" not in names


@pytest.mark.asyncio
async def test_proposals_summary_endpoint(client: AsyncClient, db_session) -> None:
    db_session.add(TiaProposal(api_name="a", status="pending"))
    db_session.add(TiaProposal(api_name="b", status="applied"))
    await db_session.commit()

    response = await client.get("/api/v1/tia/proposals/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 2
    assert data["pending"] >= 1


@pytest.mark.asyncio
async def test_list_proposals_filter_min_points_gte(client: AsyncClient, db_session) -> None:
    db_session.add(TiaProposal(api_name="income", status="pending"))
    db_session.add(TiaProposal(api_name="daily", status="pending"))
    await db_session.commit()

    response = await client.get("/api/v1/tia/proposals?min_points_gte=2000")
    assert response.status_code == 200
    names = [i["api_name"] for i in response.json()["items"]]
    assert "income" in names
    assert "daily" not in names


@pytest.mark.asyncio
async def test_list_proposals_filter_min_points_range(client: AsyncClient, db_session) -> None:
    db_session.add(TiaProposal(api_name="cn_cpi", status="pending"))
    db_session.add(TiaProposal(api_name="income", status="pending"))
    await db_session.commit()

    response = await client.get("/api/v1/tia/proposals?min_points_gte=500&min_points_lte=700")
    assert response.status_code == 200
    names = [i["api_name"] for i in response.json()["items"]]
    assert "cn_cpi" in names
    assert "income" not in names


@pytest.mark.asyncio
async def test_list_proposals_filter_points_invalid_range(client: AsyncClient) -> None:
    response = await client.get("/api/v1/tia/proposals?min_points_gte=500&min_points_lte=100")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_proposals_filter_min_points_override(client: AsyncClient, db_session) -> None:
    from app.models.tia_override import TiaOverride

    db_session.add(TiaProposal(api_name="custom_api", status="pending"))
    db_session.add(
        TiaOverride(
            api_name="custom_api",
            data_type="tushare_custom_api",
            domain="financial",
            label="Custom",
            min_points=1500,
            is_activated=False,
        )
    )
    await db_session.commit()

    response = await client.get("/api/v1/tia/proposals?min_points_gte=1000")
    assert response.status_code == 200
    names = [i["api_name"] for i in response.json()["items"]]
    assert "custom_api" in names


@pytest.mark.asyncio
async def test_get_proposal_detail(client: AsyncClient, db_session) -> None:
    p = TiaProposal(api_name="stock_basic", status="pending")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    response = await client.get(f"/api/v1/tia/proposals/{p.id}")
    assert response.status_code == 200
    assert response.json()["api_name"] == "stock_basic"
    assert response.json()["doc_id"] == 25


@pytest.mark.asyncio
async def test_update_proposal_min_points_pending(client: AsyncClient, db_session) -> None:
    p = TiaProposal(api_name="weekly", status="pending", data_type="tushare_weekly")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    response = await client.patch(
        f"/api/v1/tia/proposals/{p.id}/min-points",
        json={"min_points": 120},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["min_points"] == 120
    assert body["min_points_override"] == 120
    assert body["min_points_source"] == "manual"
    assert body["min_points_doc"] == 2000


@pytest.mark.asyncio
async def test_update_proposal_min_points_clear(client: AsyncClient, db_session) -> None:
    p = TiaProposal(
        api_name="weekly",
        status="pending",
        data_type="tushare_weekly",
        min_points_override=120,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    response = await client.patch(
        f"/api/v1/tia/proposals/{p.id}/min-points",
        json={"min_points": None},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["min_points"] == 2000
    assert body["min_points_override"] is None
    assert body["min_points_source"] == "doc_page"


@pytest.mark.asyncio
async def test_update_proposal_min_points_rejected_forbidden(client: AsyncClient, db_session) -> None:
    p = TiaProposal(api_name="weekly", status="rejected")
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    response = await client.patch(
        f"/api/v1/tia/proposals/{p.id}/min-points",
        json={"min_points": 120},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_approve_carries_min_points_override(client: AsyncClient, db_session) -> None:
    from app.models.tia_override import TiaOverride
    from sqlalchemy import select

    p = TiaProposal(
        api_name="weekly",
        status="pending",
        data_type="tushare_weekly",
        min_points_override=120,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    response = await client.patch(
        f"/api/v1/tia/proposals/{p.id}",
        json={"status": "approved", "note": "test"},
    )
    assert response.status_code == 200

    override = (
        await db_session.execute(select(TiaOverride).where(TiaOverride.api_name == "weekly"))
    ).scalar_one_or_none()
    assert override is not None
    assert override.min_points == 120


@pytest.mark.asyncio
async def test_update_proposal_min_points_with_l1_override(client: AsyncClient, db_session) -> None:
    from app.models.tia_override import TiaOverride
    from sqlalchemy import select

    db_session.add(
        TiaOverride(
            api_name="weekly",
            data_type="tushare_weekly",
            domain="market",
            label="Weekly",
            min_points=2000,
        )
    )
    p = TiaProposal(
        api_name="weekly",
        status="approved",
        data_type="tushare_weekly",
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    response = await client.patch(
        f"/api/v1/tia/proposals/{p.id}/min-points",
        json={"min_points": 120},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["min_points"] == 120
    assert body["min_points_override"] == 120
    assert body["min_points_source"] == "manual"

    override = (
        await db_session.execute(select(TiaOverride).where(TiaOverride.api_name == "weekly"))
    ).scalar_one()
    assert override.min_points == 120


@pytest.mark.asyncio
async def test_update_proposal_min_points_clear_with_l1_override(
    client: AsyncClient, db_session
) -> None:
    from app.models.tia_override import TiaOverride
    from sqlalchemy import select

    db_session.add(
        TiaOverride(
            api_name="weekly",
            data_type="tushare_weekly",
            domain="market",
            label="Weekly",
            min_points=120,
        )
    )
    p = TiaProposal(
        api_name="weekly",
        status="applied",
        data_type="tushare_weekly",
        min_points_override=120,
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)

    response = await client.patch(
        f"/api/v1/tia/proposals/{p.id}/min-points",
        json={"min_points": None},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["min_points"] == 2000
    assert body["min_points_override"] is None
    assert body["min_points_source"] == "l1_override"

    override = (
        await db_session.execute(select(TiaOverride).where(TiaOverride.api_name == "weekly"))
    ).scalar_one()
    assert override.min_points == 2000


@pytest.mark.asyncio
async def test_list_proposals_omits_heavy_spec_fields(client: AsyncClient, db_session) -> None:
    db_session.add(TiaProposal(api_name="income", status="pending", data_type="tia_income"))
    await db_session.commit()

    listed = await client.get("/api/v1/tia/proposals?limit=10")
    assert listed.status_code == 200
    item = next(i for i in listed.json()["items"] if i["api_name"] == "income")
    assert item.get("output_fields") in (None, [])
    assert item.get("input_params") in (None, [])

    detail = await client.get(f"/api/v1/tia/proposals/{item['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert len(body.get("output_fields") or []) > 0
    assert len(body.get("input_params") or []) > 0
