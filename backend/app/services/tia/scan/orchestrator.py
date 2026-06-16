"""TIA scan orchestrator: provider-agnostic index diff + batched API probe."""

from __future__ import annotations

import time
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.catalog.scan_catalog import local_api_names_sorted, local_override_min_points
from app.services.platform.job_service import PlatformJobService
from app.services.tia.api_probe_service import TiaApiProbeService
from app.services.tia.proposal_service import TiaProposalService
from app.services.tia.scan.adapters.registry import get_scan_adapter
from app.services.tia.doc_pages_sync_service import DocPagesSyncService
from app.services.tia.scan.document2_index_builder import (
    resolve_sync_doc_ids_for_scan,
    sidebar_index_metadata,
)
from app.services.tia.scan.api_spec_sync_service import ApiSpecSyncService
from app.services.tia.scan.doc_pages_sync_types import DocPagesSyncOptions
from app.services.tia.scan.doc_points_resolver import list_doc_ids_needing_live_fetch
from app.services.tia.scan.probe_planner import plan_probe_apis
from app.services.tia.scan.scan_points_coverage import build_scan_points_coverage
from app.services.tia.scan.tushare_sdk_discovery import (
    TushareSdkDiscoveryService,
    inspect_tushare_sdk,
    sdk_invalid_api_set,
)
from app.services.tia.scan.types import CatalogDiffResult, ScanOptions


ProgressFn = Callable[[int, str], None]


class TiaScanOrchestrator:
    def __init__(
        self,
        job_service: PlatformJobService | None = None,
        proposal_service: TiaProposalService | None = None,
        probe_service: TiaApiProbeService | None = None,
    ) -> None:
        self._jobs = job_service or PlatformJobService()
        self._proposals = proposal_service or TiaProposalService()
        self._probe = probe_service or TiaApiProbeService()

    def run(
        self,
        session: Session,
        job_id: int,
        options: ScanOptions,
        progress: ProgressFn,
    ) -> dict[str, Any]:
        adapter = get_scan_adapter(options.provider)

        progress(5, f"Phase P0: start {options.provider} scan (mode={options.mode})")
        session.commit()

        sdk_package: dict[str, Any] | None = None
        if options.provider == "tushare":
            sdk_package = inspect_tushare_sdk().to_dict()
            progress(6, f"SDK package {sdk_package.get('tushare_version')} inspected")
            session.commit()

        doc_pages_sync: dict[str, Any] | None = None
        if options.provider == "tushare" and options.sync_doc_pages:
            doc_pages_sync = self._maybe_sync_doc_pages(session, options, progress)
            session.commit()

        local_apis = local_api_names_sorted(session) if options.provider == "tushare" else []
        progress(15, f"Phase P1: loaded {len(local_apis)} local APIs")
        session.commit()

        official_snapshot = adapter.load_official_index(options)
        official_apis = official_snapshot.api_names()
        official_map = official_snapshot.as_map()
        progress(
            30,
            f"Phase P1: {len(getattr(official_snapshot, 'doc_ids_traversed', []) or official_apis)} menu doc_ids, "
            f"{len(official_apis)} APIs ({official_snapshot.source})",
        )
        session.commit()
        time.sleep(0.02)

        sdk_discovery: dict[str, Any] | None = None
        if options.provider == "tushare":
            if options.sync_sdk_scan:
                sdk_discovery = self._maybe_sdk_batch_validate(
                    session,
                    options,
                    adapter,
                    official_apis=official_apis,
                    official_map=official_map,
                    local_apis=local_apis,
                    sdk_package=sdk_package,
                    progress=progress,
                )
            elif sdk_package:
                sdk_discovery = {
                    "package": sdk_package,
                    "skipped": True,
                    "reason": "sync_sdk_scan=false",
                }
            session.commit()

        doc_specs_sync: dict[str, Any] | None = None
        if options.provider == "tushare" and options.sync_doc_specs:
            doc_specs_sync = self._maybe_sync_doc_specs(
                session,
                options,
                official_snapshot,
                adapter,
                progress,
                sdk_discovery=sdk_discovery,
            )
            session.commit()

        diff = self._diff(local_apis, official_apis, official_snapshot)
        progress(55, "Phase P2: catalog diff")
        session.commit()
        time.sleep(0.02)

        proposals_created = 0
        proposals_reconciled = 0
        if options.provider == "tushare":
            proposals_reconciled = self._proposals.reconcile_local_catalog_proposals_sync(
                session, diff.local_apis
            )
            proposals_created = self._proposals.upsert_from_scan_sync(
                session, job_id, diff.new_on_official
            )
        proposals_pending = (
            self._proposals.count_pending_sync(session) if options.provider == "tushare" else 0
        )

        probe_apis, planner_meta = plan_probe_apis(
            local_apis=diff.local_apis,
            new_on_official=diff.new_on_official,
            unchanged=diff.unchanged,
            official_map=official_map,
            options=options,
            sdk_invalid_apis=sdk_invalid_api_set(sdk_discovery),
        )
        progress(65, f"Phase P3–P4: probe plan {planner_meta.get('planned', 0)} APIs")
        session.commit()

        creds = adapter.resolve_credentials(session)
        override_points = (
            local_override_min_points(session) if options.provider == "tushare" else {}
        )
        api_probes: list[dict[str, Any]] = []
        probe_summary: dict[str, int] = {
            "ok": 0,
            "doc_field_mismatch": 0,
            "failed": 0,
            "skipped": 0,
            "points_doc_mismatch": 0,
            "total": 0,
        }

        if probe_apis and options.probe:
            progress(70, f"Phase P4: probing {len(probe_apis)} APIs")
            session.commit()

            def on_probe(api: str, row: dict[str, Any], idx: int, total: int) -> None:
                pct = 70 + int(25 * idx / max(total, 1))
                progress(pct, f"Probed {api}: {row.get('status')}")
                session.commit()

            api_probes = self._probe.probe_catalog_apis(
                probe_apis,
                token=creds.get("token"),
                account_points=int(creds.get("account_points") or 0),
                max_calls_per_minute=creds.get("max_calls_per_minute"),
                official_map=official_map,
                override_points=override_points or None,
                on_progress=on_probe,
            )
            probe_summary = TiaApiProbeService.summarize(api_probes)

        probe_msg = (
            f"probes ok={probe_summary['ok']} "
            f"mismatch={probe_summary['doc_field_mismatch']} "
            f"failed={probe_summary['failed']} "
            f"skipped={probe_summary['skipped']}"
        )
        scan_message = (
            f"Scan complete: {len(diff.new_on_official)} new, "
            f"{len(diff.missing_from_official)} local-only; {probe_msg}"
        )
        progress(100, scan_message)

        result: dict[str, Any] = {
            **diff.to_dict(),
            "scan_options": options.to_dict(),
            "provider": options.provider,
            "unresolved_doc_ids": getattr(official_snapshot, "unresolved_doc_ids", [])[:100],
            "unresolved_doc_ids_total": len(getattr(official_snapshot, "unresolved_doc_ids", []) or []),
            "local_override_count": len(diff.local_apis) if options.provider == "tushare" else 0,
            "proposals_created": proposals_created,
            "proposals_reconciled": proposals_reconciled,
            "proposals_pending": proposals_pending,
            "proposal_hints": [
                {"api": api, "action": "review", "reason": "new_on_official"}
                for api in diff.new_on_official[:50]
            ],
            "local_only_hints": [
                {"api": api, "action": "review", "reason": "local_only_not_on_official_index"}
                for api in diff.missing_from_official[:50]
            ],
            "new_on_official_sample": diff.new_on_official[:30],
            "missing_from_official_sample": diff.missing_from_official[:30],
            "probe_planner": planner_meta,
            "scan_credentials": {
                "source_id": creds.get("source_id"),
                "source_name": creds.get("source_name"),
                "account_points": creds.get("account_points"),
                "max_calls_per_minute": creds.get("max_calls_per_minute"),
                "has_token": bool(creds.get("token")),
                "note": creds.get("note"),
            },
            "api_probes": api_probes,
            "api_probe_summary": probe_summary,
            "doc_pages_sync": doc_pages_sync,
            "doc_specs_sync": doc_specs_sync,
            "sdk_discovery": sdk_discovery,
            "points_coverage": build_scan_points_coverage(
                official_snapshot,
                sync_doc_pages=options.sync_doc_pages,
                doc_pages_sync=doc_pages_sync,
                api_probes=api_probes,
            ),
            "sidebar_index": sidebar_index_metadata(official_snapshot),
            "scan_message": scan_message,
        }
        return result

    @staticmethod
    def _maybe_sdk_batch_validate(
        session: Session,
        options: ScanOptions,
        adapter,
        *,
        official_apis: list[str],
        official_map: dict[str, Any],
        local_apis: list[str],
        sdk_package: dict[str, Any] | None,
        progress: ProgressFn,
    ) -> dict[str, Any]:
        """P2: batch validate candidate APIs via live pro_api after index load."""
        progress(18, "Phase P2: SDK batch validate official index APIs…")
        creds = adapter.resolve_credentials(session)

        def sdk_progress(pct: int, msg: str) -> None:
            progress(min(28, 18 + pct // 8), msg)

        try:
            report = TushareSdkDiscoveryService().run(
                official_apis=official_apis,
                official_map=official_map,
                local_apis=local_apis,
                token=creds.get("token"),
                max_calls_per_minute=creds.get("max_calls_per_minute"),
                sleep_seconds=0.02,
                progress=sdk_progress,
            )
            if sdk_package:
                report["package"] = sdk_package
            return report
        except Exception as exc:
            progress(20, f"SDK batch validate skipped: {exc}")
            return {
                "package": sdk_package or inspect_tushare_sdk().to_dict(),
                "skipped": True,
                "reason": str(exc),
            }

    @staticmethod
    def _maybe_sync_doc_specs(
        session: Session,
        options: ScanOptions,
        official_snapshot,
        adapter,
        progress: ProgressFn,
        *,
        sdk_discovery: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Fetch wctapi markdown specs + validate APIs via tushare SDK."""
        doc_ids = list(getattr(official_snapshot, "doc_ids_traversed", []) or [])
        if not doc_ids:
            doc_ids = [
                e.doc_id
                for e in official_snapshot.apis
                if e.doc_id is not None
            ]
        if not doc_ids:
            return {"skipped": True, "reason": "no_doc_ids", "doc_ids_total": 0}

        invalid_apis = sdk_invalid_api_set(sdk_discovery)
        if invalid_apis:
            doc_map = official_snapshot.as_doc_id_map()
            doc_ids = [
                did
                for did in doc_ids
                if doc_map.get(int(did)) is None or doc_map[int(did)].api not in invalid_apis
            ]

        progress(12, f"Syncing {len(doc_ids)} API specs (wctapi md + SDK validate)…")
        creds = adapter.resolve_credentials(session)

        def spec_progress(pct: int, msg: str) -> None:
            progress(min(28, 12 + pct // 5), msg)

        try:
            result = ApiSpecSyncService().run(
                doc_ids,
                token=creds.get("token"),
                max_calls_per_minute=creds.get("max_calls_per_minute"),
                validate_sdk=True,
                write_cache=True,
                progress=spec_progress,
                skip_apis=invalid_apis or None,
            )
            if invalid_apis:
                result["skipped_sdk_invalid_apis"] = sorted(invalid_apis)[:30]
                result["skipped_sdk_invalid_count"] = len(invalid_apis)
            return result
        except Exception as exc:
            progress(14, f"Doc specs sync skipped: {exc}")
            return {
                "skipped": True,
                "reason": str(exc),
                "doc_ids_total": len(doc_ids),
            }

    @staticmethod
    def _maybe_sync_doc_pages(
        session: Session,
        options: ScanOptions,
        progress: ProgressFn,
    ) -> dict[str, Any] | None:
        """Refresh stale document/2 pages before catalog diff (best-effort)."""
        doc_ids = resolve_sync_doc_ids_for_scan(options.index_scope)
        stale = list_doc_ids_needing_live_fetch(doc_ids)
        if not stale:
            progress(8, "Doc pages cache up to date for min_points")
            return {
                "skipped": True,
                "reason": "cache_fresh",
                "stale_count": 0,
                "doc_ids_total": len(doc_ids),
            }

        progress(6, f"Syncing {len(stale)} stale doc pages for min_points…")
        try:
            sync_scope = "all" if options.index_scope == "mixed" else "resolved"
            sync_opts = DocPagesSyncOptions(
                doc_ids=stale,
                scope=sync_scope,
                rebuild_registry=True,
                patch_sidebar=True,
                reconcile_overrides=True,
            )

            def sync_progress(pct: int, msg: str) -> None:
                progress(min(14, 6 + pct // 10), msg)

            return DocPagesSyncService().run(session, sync_opts, sync_progress)
        except Exception as exc:
            progress(8, f"Doc pages sync skipped: {exc}")
            return {
                "skipped": True,
                "reason": str(exc),
                "stale_count": len(stale),
                "doc_ids_total": len(doc_ids),
            }

    @staticmethod
    def _diff(
        local_apis: list[str],
        official_apis: list[str],
        official_snapshot,
    ) -> CatalogDiffResult:
        local_set = set(local_apis)
        official_set = set(official_apis)
        return CatalogDiffResult(
            local_apis=local_apis,
            official_apis=official_apis,
            new_on_official=sorted(official_set - local_set),
            missing_from_official=sorted(local_set - official_set),
            unchanged=sorted(local_set & official_set),
            official_snapshot=official_snapshot,
        )
