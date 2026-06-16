"""Tests for proposal api_name vs wctapi doc page verification."""

import pytest

from app.models.tia_proposal import TiaProposal
from app.services.tia.proposal_doc_link_audit import audit_proposals
from app.services.tia.proposal_enrichment import (
    enrich_proposal,
    invalidate_api_meta_cache,
    verify_api_doc_link,
)


def test_verify_api_doc_link_ok_for_income() -> None:
    row = verify_api_doc_link("income")
    assert row["status"] == "ok"
    assert row["doc_id"] == 33
    assert "doc_id=33" in (row.get("doc_url") or "")


def test_verify_api_doc_link_mismatch_broker_rec() -> None:
    row = verify_api_doc_link("broker_rec", candidate_doc_id=293)
    assert row["status"] == "doc_mismatch"
    assert row["page_api"] == "cyq_perf"


def test_verify_api_doc_link_fund_portfolio() -> None:
    row = verify_api_doc_link("fund_portfolio")
    assert row["status"] == "ok"
    assert row["doc_id"] == 121


def test_enrich_proposal_hides_wrong_doc_link() -> None:
    invalidate_api_meta_cache()
    meta = enrich_proposal(TiaProposal(api_name="broker_rec", status="pending"))
    assert meta.get("doc_id") is None
    assert meta.get("doc_url") is None


def test_audit_proposals_counts() -> None:
    invalidate_api_meta_cache()
    report = audit_proposals(
        [
            TiaProposal(id=1, api_name="income", status="pending"),
            TiaProposal(id=2, api_name="broker_rec", status="pending"),
        ]
    )
    assert report.total == 2
    assert report.ok_count == 1
    assert report.doc_mismatch_count + report.no_spec_count == 1


@pytest.mark.asyncio
async def test_rename_stale_proposal_apis(db_session) -> None:
    from app.services.tia.proposal_doc_link_audit import rename_stale_proposal_apis_sync

    db_session.add(TiaProposal(api_name="st_list", status="pending", data_type="tushare_st_list"))
    db_session.add(TiaProposal(api_name="dc_daily", status="pending", data_type="tushare_dc_daily"))
    db_session.add(TiaProposal(api_name="barrelated", status="pending", data_type="tushare_barrelated"))
    await db_session.flush()

    results = await db_session.run_sync(rename_stale_proposal_apis_sync)
    by_old = {r.old_api: r for r in results}
    assert by_old["st_list"].action == "renamed"
    assert by_old["st_list"].new_api == "stock_st"
    assert by_old["barrelated"].action == "rejected_duplicate"