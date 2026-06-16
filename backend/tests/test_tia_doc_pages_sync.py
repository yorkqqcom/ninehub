"""API tests for TIA doc pages sync endpoint."""

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.mark.asyncio
async def test_doc_pages_sync_endpoint_queues_job(client: AsyncClient) -> None:
    from unittest.mock import patch

    with patch("app.api.v1.endpoints.tia.dispatch_task") as mock_dispatch:
        response = await client.post(
            "/api/v1/tia/doc-pages/sync",
            json={
                "scope": "all",
                "doc_ids": [26, 28],
                "dry_run": True,
            },
        )
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        mock_dispatch.assert_called_once()
        assert mock_dispatch.call_args[0][1] == job_id
        sync_opts = mock_dispatch.call_args[0][2]
        assert sync_opts["doc_ids"] == [26, 28]
        assert sync_opts["dry_run"] is True


def test_doc_pages_sync_execute_via_tia_service() -> None:
    from unittest.mock import patch

    from app.models.base import Base
    from app.services.platform.job_service import PlatformJobService
    from app.services.tia.scan.doc_pages_sync_types import DocPagesSyncOptions
    from app.services.tia.service import TIAService

    def mock_fetch(doc_ids, **kwargs):
        return {
            str(d): {
                "api": "trade_cal" if d == 26 else "adj_factor",
                "min_points": 2000,
                "fetcher": "mock",
            }
            for d in doc_ids
        }

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    job = PlatformJobService().create_sync(session, "tia_doc_pages_sync")
    session.commit()

    opts = DocPagesSyncOptions(
        doc_ids=[26, 28],
        rebuild_registry=False,
        patch_sidebar=False,
        reconcile_overrides=False,
        dry_run=True,
    )
    with patch(
        "app.services.tia.doc_pages_sync_service.fetch_doc_pages",
        side_effect=mock_fetch,
    ):
        result = TIAService().execute_doc_pages_sync_sync(session, job.id, opts)

    assert result["merge_stats"]["with_points"] == 2
    updated = session.get(type(job), job.id)
    assert updated.status == "success"
    assert updated.progress == 100
    session.close()
