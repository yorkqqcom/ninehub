#!/usr/bin/env python3
"""Bootstrap Shenwan (申万) industry data for Data Browser.

Activates and collects:
  - index_classify   (doc 181, 2000 pts) — SW2021 industry tree L1/L2/L3
  - index_member_all (doc 335, 2000 pts) — stock ↔ Shenwan mapping

Requires Tushare account >= 2000 points. Does NOT use index_member (指数成分).

Run:
  cd backend && python scripts/bootstrap_browser_shenwan.py
  python scripts/bootstrap_browser_shenwan.py --collect-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from browser_bootstrap_lib import db_session

from app.models.platform_job import PlatformJob  # noqa: F401
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal  # noqa: F401
from app.models.user import User  # noqa: F401
from app.services.collectors.tushare import TushareCollector
from app.services.platform.job_service import PlatformJobService
from app.services.tia.activation_service import TiaActivationService
from app.services.tia.constants import api_to_data_type
from app.services.tia.credentials import require_tushare_token, resolve_tushare_scan_credentials
from app.services.tia.override_service import TiaOverrideService
from app.services.tia.scan.tushare_doc_registry import resolve_api_meta
from app.services.tia.tia_data_loader import TiaDataLoader

SHENWAN_APIS = ("index_classify", "index_member_all")
MIN_POINTS = 2000
SW_SRC = "SW2021"


def _ensure_proposal(session: Session, api_name: str) -> TiaProposal:
    row = session.execute(
        select(TiaProposal)
        .where(TiaProposal.api_name == api_name)
        .order_by(TiaProposal.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is not None:
        return row
    meta = resolve_api_meta(api_name)
    proposal = TiaProposal(
        api_name=api_name,
        status="pending",
        action="review",
        reason="browser_shenwan_bootstrap",
        data_type=api_to_data_type(api_name),
    )
    session.add(proposal)
    session.flush()
    print(f"  created proposal for {api_name} id={proposal.id} min_points={meta.get('min_points')}")
    return proposal


def _approve_if_pending(session: Session, proposal: TiaProposal) -> None:
    if proposal.status != "pending":
        return
    admin_id = session.execute(text("select id from users where role='admin' limit 1")).scalar()
    if admin_id is None:
        raise RuntimeError("No admin user found; run init_db.py first")
    proposal.status = "approved"
    proposal.approved_by_id = int(admin_id)
    session.flush()
    print(f"  approved {proposal.api_name} id={proposal.id}")


def _activate_sync(session: Session, proposal_id: int, *, reapply: bool) -> dict:
    jobs = PlatformJobService()
    job = jobs.create_sync(session, "tia_activate")
    job.result_json = {"proposal_id": proposal_id, "reapply": reapply}
    session.commit()
    return TiaActivationService().execute_activation_sync(session, job.id)


def _get_override(session: Session, api_name: str) -> TiaOverride | None:
    return session.execute(
        select(TiaOverride).where(TiaOverride.api_name == api_name).limit(1)
    ).scalar_one_or_none()


def _schema(override: TiaOverride) -> dict:
    return dict((override.override_json or {}).get("schema") or {})


def _check_account_points(session: Session) -> int:
    creds = resolve_tushare_scan_credentials(session)
    points = int(creds.get("account_points") or 0)
    print(f"Tushare account points: {points} (required {MIN_POINTS} for Shenwan APIs)")
    if points < MIN_POINTS:
        print(
            f"  WARN: 积分不足 {MIN_POINTS}，index_classify / index_member_all 调用可能失败。"
            " 可在 .env 设置 TUSHARE_ACCOUNT_POINTS 或在数据源配置积分档位。"
        )
    require_tushare_token(creds)
    return points


def _si_code(raw: str) -> str:
    code = str(raw).strip()
    if not code:
        return code
    return code if code.endswith(".SI") else f"{code}.SI"


def _collect_index_classify(
    session: Session,
    collector: TushareCollector,
    loader: TiaDataLoader,
    override: TiaOverride,
) -> int:
    schema = _schema(override)
    table = override.table_name or "tushare_index_classify"
    frames: list[pd.DataFrame] = []
    for level in ("L1", "L2", "L3"):
        print(f"  index_classify level={level} src={SW_SRC} …")
        df = collector._call_pro("index_classify", level=level, src=SW_SRC)  # noqa: SLF001
        if df is not None and not df.empty:
            frames.append(df)
            print(f"    -> {len(df)} rows")
    if not frames:
        print("  index_classify: no data returned")
        return 0
    merged = pd.concat(frames, ignore_index=True)
    count = loader.upsert_dataframe(session, table, schema, merged)
    session.commit()
    print(f"  index_classify upserted {count} rows into {table}")
    return count


def _l1_codes_from_classify(session: Session, table: str) -> list[str]:
    cols = session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t ORDER BY ordinal_position"
        ),
        {"t": table},
    ).fetchall()
    colset = {c[0] for c in cols}
    # index_code 为 API 入参格式（801010.SI）；industry_code 为内部编码（110000）
    code_col = "index_code" if "index_code" in colset else "industry_code"
    src_filter = " AND src = :src" if "src" in colset else ""
    params: dict = {"src": SW_SRC}
    rows = session.execute(
        text(
            f'SELECT DISTINCT "{code_col}" AS code FROM "{table}" '
            f"WHERE level = 'L1'{src_filter} ORDER BY 1"
        ),
        params,
    ).fetchall()
    return [_si_code(r[0]) for r in rows if r[0]]


def _collect_index_member_all(
    session: Session,
    collector: TushareCollector,
    loader: TiaDataLoader,
    override: TiaOverride,
    *,
    classify_table: str,
) -> int:
    schema = _schema(override)
    table = override.table_name or "tushare_index_member_all"
    l1_codes = _l1_codes_from_classify(session, classify_table)
    if not l1_codes:
        print("  index_member_all: no L1 codes in classify table; run classify collect first")
        return 0

    frames: list[pd.DataFrame] = []
    for l1 in l1_codes:
        print(f"  index_member_all l1_code={l1} …")
        df = collector._call_pro("index_member_all", l1_code=l1, is_new="Y")  # noqa: SLF001
        if df is not None and not df.empty:
            frames.append(df)
            print(f"    -> {len(df)} rows")

    if not frames:
        print("  index_member_all: no data returned")
        return 0
    merged = pd.concat(frames, ignore_index=True)
    count = loader.upsert_dataframe(session, table, schema, merged)
    session.commit()
    print(f"  index_member_all upserted {count} rows into {table}")
    return count


def _row_count(session: Session, table: str) -> int:
    try:
        return int(session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one())
    except Exception:
        return -1


def bootstrap(*, activate: bool, collect: bool) -> int:
    session = db_session()
    failed = 0

    print("=== Shenwan bootstrap (index_classify + index_member_all) ===")
    for api in SHENWAN_APIS:
        meta = resolve_api_meta(api)
        pts = meta.get("min_points")
        print(f"  {api}: doc_id={meta.get('doc_id')} min_points={pts}")

    if collect:
        try:
            _check_account_points(session)
        except Exception as exc:
            print(f"ERROR credentials: {exc}")
            session.close()
            return 1

    if activate:
        for api in SHENWAN_APIS:
            print(f"\n=== activate {api} ===")
            try:
                proposal = _ensure_proposal(session, api)
                print(f"  proposal id={proposal.id} status={proposal.status}")
                if proposal.status == "applied":
                    print("  already applied")
                    continue
                _approve_if_pending(session, proposal)
                session.commit()
                reapply = proposal.status in ("applied", "failed")
                result = _activate_sync(session, proposal.id, reapply=reapply)
                status = session.execute(
                    text("select status from tia_proposals where id=:id"),
                    {"id": proposal.id},
                ).scalar()
                print(f"  activation -> {status}, data_type={result.get('data_type')}")
                for step, meta in (result.get("steps") or {}).items():
                    if isinstance(meta, dict) and meta.get("status") == "failed":
                        print(f"    FAIL {step}: {meta.get('error', '')[:300]}")
                if status != "applied":
                    failed += 1
            except Exception as exc:
                session.rollback()
                failed += 1
                print(f"  ERROR: {exc}")

    if collect:
        print("\n=== collect Shenwan tables ===")
        TiaOverrideService().load_all_into_registry_sync(session)
        creds = resolve_tushare_scan_credentials(session)
        token = require_tushare_token(creds)
        mcpm = creds.get("max_calls_per_minute")
        collector = TushareCollector(
            token=token,
            max_calls_per_minute=int(mcpm) if mcpm else None,
        )
        loader = TiaDataLoader()

        classify_ov = _get_override(session, "index_classify")
        member_ov = _get_override(session, "index_member_all")
        if classify_ov is None or not classify_ov.is_activated:
            print("ERROR: index_classify not activated")
            session.close()
            return 1
        if member_ov is None or not member_ov.is_activated:
            print("ERROR: index_member_all not activated")
            session.close()
            return 1

        try:
            _collect_index_classify(session, collector, loader, classify_ov)
        except Exception as exc:
            failed += 1
            session.rollback()
            print(f"  ERROR index_classify: {exc}")

        classify_table = classify_ov.table_name or "tushare_index_classify"
        try:
            _collect_index_member_all(
                session,
                collector,
                loader,
                member_ov,
                classify_table=classify_table,
            )
        except Exception as exc:
            failed += 1
            session.rollback()
            print(f"  ERROR index_member_all: {exc}")

    print("\n=== readiness ===")
    for api in SHENWAN_APIS:
        ov = _get_override(session, api)
        if ov and ov.table_name:
            cnt = _row_count(session, ov.table_name)
            print(f"  {ov.table_name}: {cnt} rows")

    session.close()
    print(f"\nDone. failed={failed}")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap Shenwan industry for Data Browser")
    parser.add_argument(
        "--activate-only",
        action="store_true",
        help="Only TIA activate index_classify + index_member_all",
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Skip activation; collect into activated tables",
    )
    args = parser.parse_args()
    activate = not args.collect_only
    collect = not args.activate_only
    raise SystemExit(bootstrap(activate=activate, collect=collect))


if __name__ == "__main__":
    main()
