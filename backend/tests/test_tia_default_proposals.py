"""Tests for bundled default TIA proposal seed."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.tia_proposal import TiaProposal
from app.services.tia.default_proposal_seed import (
    build_default_proposals_payload,
    seed_default_proposals_sync,
)


def test_build_default_proposals_payload_stock_a() -> None:
    payload = build_default_proposals_payload(index_scope="stock_a")
    assert payload["index_scope"] == "stock_a"
    assert payload["official_count"] >= 50
    assert len(payload["items"]) >= 50
    assert all(item["api_name"] for item in payload["items"])
    with_points = sum(1 for item in payload["items"] if item.get("min_points") is not None)
    assert with_points >= 40


def test_enrich_proposal_min_points_top10_holders() -> None:
    from app.models.tia_proposal import TiaProposal
    from app.services.tia.proposal_enrichment import build_api_meta_map, enrich_proposal

    proposal = TiaProposal(api_name="top10_holders", status="pending", data_type="tushare_top10_holders")
    meta = build_api_meta_map()
    extra = enrich_proposal(proposal, meta)
    assert extra.get("min_points") == 2000
    assert extra.get("min_points_doc") == 2000


def test_seed_default_proposals_only_when_empty() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    first = seed_default_proposals_sync(session)
    session.commit()
    assert first >= 50

    second = seed_default_proposals_sync(session)
    session.commit()
    assert second == 0

    count = session.query(TiaProposal).count()
    assert count == first
    session.close()
