"""Probe planner doc_id traversal tests."""

from app.services.tia.scan.probe_planner import plan_probe_apis
from app.services.tia.scan.types import OfficialApiEntry, ScanOptions


def test_plan_probe_all_traverses_doc_id_order() -> None:
    official_map = {
        "daily": OfficialApiEntry(api="daily", doc_id=27, probe_category="ts_code_date_range"),
        "stock_basic": OfficialApiEntry(api="stock_basic", doc_id=25, probe_category="list_basic"),
    }
    opts = ScanOptions(probe=True, probe_scope="all", probe_limit=500)
    planned, meta = plan_probe_apis(
        local_apis=["daily"],
        new_on_official=["stock_basic"],
        unchanged=[],
        official_map=official_map,
        options=opts,
    )
    assert meta["traversal"] == "doc_id_asc"
    assert planned[0] == "stock_basic"
    assert planned[1] == "daily"


def test_plan_probe_skips_sdk_invalid_apis() -> None:
    official_map = {
        "daily": OfficialApiEntry(api="daily", doc_id=27, probe_category="ts_code_date_range"),
        "pro": OfficialApiEntry(api="pro", doc_id=58, probe_category="ts_code_date_range"),
    }
    opts = ScanOptions(probe=True, probe_scope="all", probe_limit=500)
    planned, meta = plan_probe_apis(
        local_apis=[],
        new_on_official=[],
        unchanged=["daily", "pro"],
        official_map=official_map,
        options=opts,
        sdk_invalid_apis={"pro"},
    )
    assert "pro" not in planned
    assert meta["skipped_sdk_invalid"] >= 1
