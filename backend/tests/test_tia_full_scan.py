"""TIA full scan orchestrator tests."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.services.platform.job_service import PlatformJobService
from app.services.tia.scan.orchestrator import TiaScanOrchestrator
from app.services.tia.scan.types import ScanOptions


def _fast_scan_opts(**kwargs) -> ScanOptions:
    """Orchestrator tests: no live probe / SDK batch / wctapi network."""
    base = dict(
        probe=False,
        sync_sdk_scan=False,
        sync_doc_specs=False,
        sync_doc_pages=False,
    )
    base.update(kwargs)
    return ScanOptions(**base)


def test_full_scan_loads_doc14_official_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job = PlatformJobService().create_sync(session, "tia_scan")
    session.commit()

    opts = _fast_scan_opts(mode="full", index_source="doc14", index_scope="stock_a")
    result = TiaScanOrchestrator().run(session, job.id, opts, lambda _p, _m: None)

    assert result["official_count"] >= 60
    assert result["official_index_source"] == "doc14_catalog"
    assert result["official_index_scope"] == "stock_a"
    session.close()


def test_full_scan_auto_prefers_document2_sidebar() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job = PlatformJobService().create_sync(session, "tia_scan")
    session.commit()

    opts = _fast_scan_opts(mode="full", index_source="auto", index_scope="stock_a")
    result = TiaScanOrchestrator().run(session, job.id, opts, lambda _p, _m: None)

    assert result["official_index_source"] == "document2_sidebar_bundled"
    assert result["official_count"] >= 50
    assert result.get("doc_ids_traversed", 0) >= 90
    assert result["official_count"] >= 20
    assert result.get("sdk_discovery", {}).get("package", {}).get("tushare_version")
    session.close()


def test_full_scan_loads_bundled_official_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job = PlatformJobService().create_sync(session, "tia_scan")
    session.commit()

    opts = _fast_scan_opts(mode="full", index_source="bundled", index_scope="stock_a")
    result = TiaScanOrchestrator().run(session, job.id, opts, lambda _p, _m: None)

    assert result["official_count"] >= 60
    assert result["official_index_scope"] == "stock_a"
    assert len(result["new_on_official"]) >= 55
    assert result["scan_options"]["mode"] == "full"
    session.close()


def test_full_scan_mixed_bundled_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job = PlatformJobService().create_sync(session, "tia_scan")
    session.commit()

    opts = _fast_scan_opts(mode="full", index_source="bundled", index_scope="mixed")
    result = TiaScanOrchestrator().run(session, job.id, opts, lambda _p, _m: None)

    assert result["official_count"] == 53
    session.close()


def test_full_scan_probe_points_no_false_mismatch() -> None:
    """catalog vs official doc min_points should align when both are doc-first."""
    from app.services.tia.api_probe_service import _local_catalog_min_points
    from app.services.tia.scan.document2_index_builder import build_document2_official_index
    from app.services.tia.scan.tushare_doc_registry import resolve_min_points_for_doc_id

    snap = build_document2_official_index(index_scope="stock_a")
    mismatches: list[str] = []
    for api in snap.api_names():
        catalog_pts = _local_catalog_min_points(api)
        entry = snap.as_map()[api]
        if entry.doc_id is None:
            continue
        official_pts, _ = resolve_min_points_for_doc_id(int(entry.doc_id))
        if catalog_pts is not None and official_pts is not None and int(catalog_pts) != int(official_pts):
            mismatches.append(api)
    assert mismatches == []


def test_catalog_mode_uses_full_index() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job = PlatformJobService().create_sync(session, "tia_scan")
    session.commit()

    opts = _fast_scan_opts(mode="catalog", index_source="bundled", index_scope="mixed")
    result = TiaScanOrchestrator().run(session, job.id, opts, lambda _p, _m: None)

    assert result["official_count"] == 53
    assert result["local_count"] == 0
    session.close()
