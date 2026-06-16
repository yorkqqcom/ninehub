"""trade_cal probe spec should use cal_date, not trade_date."""

from app.services.tia.scan.probe_planner import resolve_probe_spec
from app.services.tia.scan.types import OfficialApiEntry


def test_trade_cal_uses_cal_date_template_not_trade_date() -> None:
    entry = OfficialApiEntry(
        api="trade_cal",
        doc_id=26,
        probe_category="trade_date",
        min_points=120,
    )
    spec, source, pts = resolve_probe_spec("trade_cal", entry)
    assert spec is not None
    assert source == "template:trade_cal"
    assert pts == 120
    assert "cal_date" in spec["expected_fields"]
    assert "trade_date" not in spec["expected_fields"]
    assert spec["params"]["exchange"] == "SSE"
