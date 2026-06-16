"""Tests for proposal enrichment."""

from app.models.tia_proposal import TiaProposal
from app.services.tia.proposal_enrichment import enrich_proposal


def test_enrich_proposal_from_catalog() -> None:
    p = TiaProposal(api_name="income", status="pending")
    meta = enrich_proposal(p)
    assert meta["doc_id"] == 33
    assert meta["min_points"] == 600
    assert meta["doc_url"] and "doc_id=33" in meta["doc_url"]
