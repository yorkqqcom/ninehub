"""Orchestrator SDK-first scan integration tests."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.services.platform.job_service import PlatformJobService
from app.services.tia.scan.orchestrator import TiaScanOrchestrator
from app.services.tia.scan.types import ScanOptions


def test_full_scan_includes_sdk_discovery_package(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job = PlatformJobService().create_sync(session, "tia_scan")
    session.commit()

    monkeypatch.setattr(
        "app.services.tia.scan.orchestrator.TushareSdkDiscoveryService.run",
        lambda self, **kwargs: {
            "package": {"tushare_version": "9.9.9"},
            "skipped": False,
            "validated_count": 2,
            "valid_count": 2,
            "invalid_count": 0,
            "valid_apis": ["daily"],
            "invalid_apis": [],
        },
    )
    monkeypatch.setattr(
        "app.services.tia.scan.orchestrator.ApiSpecSyncService.run",
        lambda self, *a, **k: {"synced_count": 0, "doc_ids_total": 0},
    )

    opts = ScanOptions(
        mode="full",
        probe=False,
        sync_sdk_scan=True,
        sync_doc_specs=False,
        index_source="document2",
        index_scope="stock_a",
    )
    result = TiaScanOrchestrator().run(session, job.id, opts, lambda _p, _m: None)

    assert result.get("sdk_discovery") is not None
    assert result["sdk_discovery"]["package"]["tushare_version"]
    session.close()


def test_full_scan_sdk_package_inspected_without_batch(monkeypatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job = PlatformJobService().create_sync(session, "tia_scan")
    session.commit()

    opts = ScanOptions(
        mode="full",
        probe=False,
        sync_sdk_scan=False,
        sync_doc_specs=False,
        index_source="document2",
        index_scope="stock_a",
    )
    result = TiaScanOrchestrator().run(session, job.id, opts, lambda _p, _m: None)

    sdk = result.get("sdk_discovery")
    assert sdk is not None
    assert sdk.get("skipped") is True
    assert sdk.get("package", {}).get("tushare_version")
    session.close()
