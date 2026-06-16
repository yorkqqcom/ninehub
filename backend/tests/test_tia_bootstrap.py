"""TIA runtime bootstrap tests."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.catalog.registry import CATALOG_REGISTRY, get_data_type_entry
from app.models.base import Base
from app.models.tia_override import TiaOverride
from app.services.tia.override_service import TiaOverrideService
from app.sync.bootstrap import bootstrap_tia_runtime
from app.sync.handlers import DATA_TYPE_HANDLERS


def test_bootstrap_restores_handler_and_schema_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    schema = {
        "columns": [
            {"key": "stock_code", "label": "代码", "type": "string"},
            {"key": "trade_date", "label": "日期", "type": "date"},
            {"key": "close", "label": "收盘", "type": "number"},
        ],
        "unique_keys": ["stock_code", "trade_date"],
        "collect": {"max_codes_per_run": 10, "max_api_calls_per_run": 50},
    }
    session.add(
        TiaOverride(
            api_name="daily",
            data_type="tia_daily",
            domain="market",
            label="日线",
            min_points=120,
            table_name="tia_daily",
            is_activated=True,
            override_json={"schema": schema, "browse_enabled": False},
        )
    )
    session.commit()

    DATA_TYPE_HANDLERS.pop("tia_daily", None)
    CATALOG_REGISTRY.pop("tia_daily", None)

    count = bootstrap_tia_runtime(session)
    assert count == 1
    assert "tia_daily" in DATA_TYPE_HANDLERS
    entry = get_data_type_entry("tia_daily")
    assert entry is not None
    assert len(entry.columns) == 3
    session.close()
    DATA_TYPE_HANDLERS.pop("tia_daily", None)
    CATALOG_REGISTRY.pop("tia_daily", None)
