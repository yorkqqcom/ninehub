"""Reconcile tia_overrides min_points/doc_url with canonical interface metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models.tia_override import TiaOverride  # noqa: E402
from app.services.tia.scan.tushare_doc_registry import (  # noqa: E402
    resolve_canonical_api_meta,
    resolve_min_points_for_doc_id,
)


def _canonical_for_api(api_name: str) -> dict | None:
    meta = resolve_canonical_api_meta(api_name)
    if not meta:
        return None
    doc_id = meta.get("doc_id")
    if doc_id is not None:
        pts, source = resolve_min_points_for_doc_id(int(doc_id))
        if pts is not None:
            meta = {**meta, "min_points": pts, "min_points_source": source}
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile TIA override points vs interface docs")
    parser.add_argument("--apply", action="store_true", help="Write fixes to database")
    parser.add_argument("--api", action="append", dest="apis", help="Limit to specific api_name")
    args = parser.parse_args()

    settings = get_settings()
    engine = create_engine(settings.sync_database_url)
    session = sessionmaker(bind=engine)()

    query = select(TiaOverride)
    overrides = list(session.execute(query).scalars().all())
    if args.apis:
        api_set = set(args.apis)
        overrides = [o for o in overrides if o.api_name in api_set]

    mismatches: list[dict] = []
    for override in overrides:
        canonical = _canonical_for_api(override.api_name)
        if not canonical:
            continue
        doc_id = canonical.get("doc_id")
        expected_url = canonical.get("doc_url") or (
            f"https://tushare.pro/document/2?doc_id={doc_id}" if doc_id else None
        )
        expected_pts = canonical.get("min_points")
        needs_pts = expected_pts is not None and int(override.min_points) != int(expected_pts)
        needs_url = expected_url and override.doc_url != expected_url
        if not needs_pts and not needs_url:
            continue
        row = {
            "api": override.api_name,
            "override_min_points": override.min_points,
            "canonical_min_points": expected_pts,
            "override_doc_url": override.doc_url,
            "canonical_doc_url": expected_url,
            "doc_id": doc_id,
            "min_points_source": canonical.get("min_points_source"),
        }
        mismatches.append(row)
        if args.apply:
            if needs_pts and expected_pts is not None:
                override.min_points = int(expected_pts)
            if needs_url and expected_url:
                override.doc_url = expected_url

    if args.apply and mismatches:
        session.commit()
        print(f"Applied {len(mismatches)} override fix(es)")
    elif mismatches:
        print(f"Found {len(mismatches)} mismatch(es) (dry-run, use --apply to fix):")
    else:
        print("All overrides match canonical interface metadata")
        session.close()
        return

    for row in mismatches:
        print(row)
    session.close()


if __name__ == "__main__":
    main()
