"""Seed default TIA proposals from bundled document/2 sidebar catalog diff."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.platform_job import PlatformJob  # noqa: F401 — FK target for TiaProposal.job_id
from app.models.tia_proposal import TiaProposal
from app.models.tia_override import TiaOverride
from app.models.user import User  # noqa: F401 — FK target for TiaProposal.approved_by_id
from app.services.tia.constants import api_to_data_type

_PROVIDERS = Path(__file__).resolve().parents[2] / "catalog" / "providers"
DEFAULT_PROPOSALS_PATH = _PROVIDERS / "tushare_default_proposals.json"


def build_default_proposals_payload(*, index_scope: str = "stock_a") -> dict:
    """Compare document/2 sidebar index vs empty local catalog (for bundled seed file)."""
    from app.services.tia.scan.tushare_doc_catalog import load_document2_sidebar_index

    from app.services.tia.proposal_enrichment import build_api_meta_map

    snap = load_document2_sidebar_index(index_scope=index_scope)
    meta_map = build_api_meta_map()
    items: list[dict] = []
    for entry in snap.apis:
        canonical = meta_map.get(entry.api, {})
        min_points = canonical.get("min_points")
        if min_points is None:
            min_points = entry.min_points
        items.append(
            {
                "api_name": entry.api,
                "data_type": api_to_data_type(entry.api),
                "reason": "new_on_official",
                "status": "pending",
                "action": "review",
                "doc_id": entry.doc_id,
                "label": entry.label or canonical.get("label"),
                "min_points": min_points,
                "min_points_source": canonical.get("min_points_source"),
                "doc_url": entry.doc_url or canonical.get("doc_url"),
                "category": entry.category or canonical.get("category"),
            }
        )
    items.sort(key=lambda row: (row.get("doc_id") or 99999, row["api_name"]))
    return {
        "provider": "tushare",
        "source_url": "https://tushare.pro/document/2",
        "index_scope": index_scope,
        "index_source": snap.source,
        "official_count": len(snap.apis),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
    }


def write_default_proposals_file(*, index_scope: str = "stock_a", path: Path | None = None) -> Path:
    out = path or DEFAULT_PROPOSALS_PATH
    payload = build_default_proposals_payload(index_scope=index_scope)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def seed_default_proposals_sync(session: Session) -> int:
    """Insert bundled default proposals when table is empty (init_db / first deploy)."""
    existing = int(session.execute(select(func.count()).select_from(TiaProposal)).scalar_one())
    if existing > 0:
        return 0
    if not DEFAULT_PROPOSALS_PATH.is_file():
        return 0

    payload = json.loads(DEFAULT_PROPOSALS_PATH.read_text(encoding="utf-8"))
    local_apis = set(session.execute(select(TiaOverride.api_name)).scalars().all())
    created = 0
    for item in payload.get("items", []):
        api = str(item["api_name"])
        if api in local_apis:
            continue
        session.add(
            TiaProposal(
                api_name=api,
                status=str(item.get("status") or "pending"),
                action=str(item.get("action") or "review"),
                reason=str(item.get("reason") or "new_on_official"),
                data_type=item.get("data_type") or api_to_data_type(api),
            )
        )
        created += 1
    session.flush()
    return created
