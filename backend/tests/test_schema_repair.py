"""Schema repair and migration sync tests."""

from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker

import pytest

from app.core.exceptions import ValidationError

from app.models.base import Base
from app.models.sync_task import SyncTask
from app.models.task_run import TaskRun
from app.models.tia_override import TiaOverride
from app.services.catalog.canonical_standard import build_canonical_schema
from app.services.tia.migration_service import TiaMigrationService
from app.services.tia.schema_maintenance_service import TiaSchemaMaintenanceService
from app.services.tia.schema_repair_service import TiaSchemaRepairService
from app.services.tasks.run_service import TaskRunService


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_sync_table_schema_creates_browse_indexes() -> None:
    session = _session()
    schema = build_canonical_schema("daily")
    migration = TiaMigrationService()
    migration.ensure_table(session, "tia_daily_idx", schema)
    synced = migration.sync_table_schema(session, "tia_daily_idx", schema)
    session.commit()

    inspector = inspect(session.get_bind())
    index_names = {idx["name"] for idx in inspector.get_indexes("tia_daily_idx")}
    uq_names = {i["name"] for i in schema.get("indexes", []) if i.get("unique")}
    assert uq_names & index_names
    assert any(n.startswith("ix_") for n in index_names)


def test_sync_table_schema_adds_missing_columns() -> None:
    session = _session()
    wrong_schema = {
        "columns": [
            {"key": "trade_date", "type": "date", "nullable": False},
        ],
        "unique_keys": ["trade_date"],
    }
    migration = TiaMigrationService()
    migration.ensure_table(session, "tia_trade_cal_repair", wrong_schema)

    correct = build_canonical_schema("trade_cal")
    synced = migration.sync_table_schema(session, "tia_trade_cal_repair", correct)
    session.commit()

    assert "cal_date" in synced["columns_added"] or "exchange" in synced["columns_added"]
    inspector = inspect(session.get_bind())
    col_names = {c["name"] for c in inspector.get_columns("tia_trade_cal_repair")}
    assert "cal_date" in col_names
    assert "exchange" in col_names
    session.close()


def test_repair_trade_cal_override_updates_schema() -> None:
    session = _session()
    wrong_schema = {
        "columns": [{"key": "trade_date", "type": "date", "nullable": False, "api_field": "trade_date"}],
        "unique_keys": ["trade_date"],
        "field_mappings": {"trade_date": "trade_date"},
        "api_fields": ["trade_date"],
        "data_standard": {"approved": True},
    }
    override = TiaOverride(
        api_name="trade_cal",
        data_type="trade_cal",
        domain="基础",
        label="交易日历",
        table_name="tia_trade_cal_repair2",
        is_activated=True,
        override_json={"schema": wrong_schema},
    )
    session.add(override)
    session.add(
        SyncTask(
            name="TIA:trade_cal",
            data_type="trade_cal",
            status="active",
            schedule_cron="0 18 * * 1-5",
        )
    )
    session.flush()
    session.commit()

    result = TiaSchemaRepairService().repair_api_sync(session, "trade_cal")
    session.commit()

    assert "cal_date" in result["columns_after"]
    assert result["unique_keys_after"] == ["exchange", "cal_date"]
    assert result["collect_mode"] == "exchange_date_range"
    assert result["schedule_cron"] == "0 8 * * 1"

    refreshed = session.get(TiaOverride, override.id)
    schema = (refreshed.override_json or {}).get("schema") or {}
    assert schema["unique_keys"] == ["exchange", "cal_date"]
    session.close()


def test_incremental_ignores_zero_row_success() -> None:
    session = _session()
    task = SyncTask(name="t", data_type="trade_cal", status="active")
    session.add(task)
    session.flush()

    session.add(
        TaskRun(
            task_id=task.id,
            status="success",
            rows_upserted=100,
            result_json={"collect_end_date": "2026-06-01"},
        )
    )
    session.add(
        TaskRun(
            task_id=task.id,
            status="success",
            rows_upserted=0,
            result_json={"collect_end_date": "2026-06-13"},
        )
    )
    session.flush()

    start, _end = TaskRunService()._resolve_collect_dates(session, task, "2020-01-01")
    assert start.isoformat() == "2026-06-02"
    session.close()


def test_incremental_uses_global_start_when_only_zero_row_success() -> None:
    session = _session()
    task = SyncTask(name="t2", data_type="trade_cal", status="active")
    session.add(task)
    session.flush()

    session.add(
        TaskRun(
            task_id=task.id,
            status="success",
            rows_upserted=0,
            result_json={"collect_end_date": "2026-06-13"},
        )
    )
    session.flush()

    start, _end = TaskRunService()._resolve_collect_dates(session, task, "2020-01-01")
    assert start.isoformat() == "2020-01-01"
    session.close()


def _trade_cal_wrong_override(session, *, table_name: str = "tia_trade_cal_plan") -> TiaOverride:
    wrong_schema = {
        "columns": [{"key": "trade_date", "type": "date", "nullable": False, "api_field": "trade_date"}],
        "unique_keys": ["trade_date"],
        "field_mappings": {"trade_date": "trade_date"},
        "api_fields": ["trade_date"],
        "data_standard": {"approved": True},
    }
    override = TiaOverride(
        api_name="trade_cal",
        data_type="trade_cal",
        domain="基础",
        label="交易日历",
        table_name=table_name,
        is_activated=True,
        override_json={"schema": wrong_schema},
    )
    session.add(override)
    session.flush()
    return override


def test_schema_plan_trade_cal_diff() -> None:
    session = _session()
    _trade_cal_wrong_override(session)
    session.commit()

    plan = TiaSchemaMaintenanceService().plan(session, "trade_cal")
    assert plan["columns_drift"] is True
    assert plan["keys_drift"] is True
    assert "cal_date" in plan["columns_after"]
    assert plan["unique_keys_registry"] == ["exchange", "cal_date"]
    assert "columns" in plan["available_modes"]
    assert "unique_keys" in plan["available_modes"]
    session.close()


def test_schema_apply_columns_only_preserves_keys_until_unique_mode() -> None:
    session = _session()
    base = build_canonical_schema("daily")
    slim_columns = [c for c in base["columns"] if c["key"] in ("stock_code", "trade_date", "close")]
    wrong_schema = {
        **base,
        "columns": slim_columns,
        "unique_keys": ["stock_code", "trade_date"],
    }
    override = TiaOverride(
        api_name="daily",
        data_type="daily",
        domain="行情",
        label="日线",
        table_name="tia_daily_cols_only",
        is_activated=True,
        override_json={"schema": wrong_schema},
    )
    session.add(override)
    session.commit()

    svc = TiaSchemaMaintenanceService()
    result = svc.apply(session, "daily", ["columns"], confirm_risk=True)
    session.commit()

    assert len(result["columns_after"]) > len(slim_columns)
    assert result["unique_keys_after"] == ["stock_code", "trade_date"]
    oid = session.execute(select(TiaOverride).where(TiaOverride.api_name == "daily")).scalar_one().id
    refreshed = session.get(TiaOverride, oid)
    schema = (refreshed.override_json or {}).get("schema") or {}
    assert schema["unique_keys"] == ["stock_code", "trade_date"]
    session.close()


def test_schema_apply_unique_keys_requires_registry(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.tia.schema_maintenance_service.is_registry_registered",
        lambda _api: False,
    )
    session = _session()
    _trade_cal_wrong_override(session)
    session.commit()

    svc = TiaSchemaMaintenanceService()
    with pytest.raises(ValidationError, match="registry"):
        svc.apply(session, "trade_cal", ["unique_keys"], confirm_risk=True)
    session.close()


def test_schema_apply_blocked_without_confirm_when_drops() -> None:
    session = _session()
    schema = build_canonical_schema("trade_cal")
    extra_schema = {
        **schema,
        "columns": list(schema["columns"]) + [{"key": "legacy_col", "type": "string", "nullable": True}],
    }
    migration = TiaMigrationService()
    migration.ensure_table(session, "tia_trade_cal_drop", extra_schema)
    session.commit()

    override = TiaOverride(
        api_name="trade_cal",
        data_type="trade_cal_drop",
        domain="基础",
        label="Drop test",
        table_name="tia_trade_cal_drop",
        is_activated=True,
        override_json={"schema": extra_schema},
    )
    session.add(override)
    session.commit()

    svc = TiaSchemaMaintenanceService()
    plan = svc.plan(session, "trade_cal")
    assert plan["columns_dropped"]

    with pytest.raises(ValidationError, match="confirm_risk"):
        svc.apply(session, "trade_cal", ["columns"], confirm_risk=False)
    session.close()


def test_build_registry_hint_snippet() -> None:
    from app.services.tia.unique_key_registry import build_registry_hint

    hint = build_registry_hint("trade_cal", ["exchange", "cal_date", "is_open"])
    assert hint["registry_registered"] is True
    assert "trade_cal" in hint["registry_snippet"]
    assert "exchange" in hint["registry_snippet"]
