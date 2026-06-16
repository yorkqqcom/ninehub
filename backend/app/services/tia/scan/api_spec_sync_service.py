"""Sync Tushare API specs: wctapi markdown + SDK validation."""

from __future__ import annotations

import time
from typing import Any, Callable

from app.services.tia.scan.api_spec_store import load_api_specs_cache, merge_api_spec_entry
from app.services.tia.scan.doc_spec_fetcher import fetch_doc_spec
from app.services.tia.scan.probe_spec_from_doc import api_doc_spec_from_cache_row, build_probe_spec_from_doc
from app.services.tia.scan.tushare_sdk_validate import validate_api_via_sdk

ProgressFn = Callable[[int, str], None]


class ApiSpecSyncService:
    def run(
        self,
        doc_ids: list[int],
        *,
        token: str | None,
        max_calls_per_minute: int | None = None,
        sleep_seconds: float = 0.15,
        validate_sdk: bool = True,
        write_cache: bool = True,
        progress: ProgressFn | None = None,
        skip_apis: set[str] | list[str] | None = None,
    ) -> dict[str, Any]:
        total = len(doc_ids)
        synced: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        invalid_sdk: list[str] = []
        skipped_sdk_invalid: list[str] = []
        skip_set = set(skip_apis or [])

        for idx, doc_id in enumerate(doc_ids, start=1):
            if progress:
                progress(int(100 * idx / max(total, 1)), f"Spec sync doc_id={doc_id}")

            row = fetch_doc_spec(int(doc_id))
            if row.get("error"):
                errors.append(row)
                time.sleep(sleep_seconds)
                continue

            spec = api_doc_spec_from_cache_row(row)
            if spec is None:
                errors.append({**row, "error": "api_doc_spec_from_cache_row failed"})
                time.sleep(sleep_seconds)
                continue

            if spec.api in skip_set:
                skipped_sdk_invalid.append(spec.api)
                time.sleep(sleep_seconds)
                continue

            probe = build_probe_spec_from_doc(spec)
            row = spec.to_dict()
            row["probe_spec"] = {
                "params": probe.get("params"),
                "expected_fields": probe.get("expected_fields"),
            }

            if validate_sdk and token:
                validation = validate_api_via_sdk(
                    token,
                    spec.api,
                    probe.get("params") or {},
                    max_calls_per_minute=max_calls_per_minute,
                )
                row.update(validation)
                if validation.get("sdk_valid") is False:
                    invalid_sdk.append(spec.api)

            synced.append(row)
            if write_cache:
                merge_api_spec_entry(int(doc_id), row)
            time.sleep(sleep_seconds)

        return {
            "doc_ids_total": total,
            "synced_count": len(synced),
            "error_count": len(errors),
            "invalid_sdk_count": len(invalid_sdk),
            "invalid_sdk_apis": invalid_sdk[:30],
            "skipped_sdk_invalid_count": len(skipped_sdk_invalid),
            "skipped_sdk_invalid_apis": skipped_sdk_invalid[:30],
            "errors_sample": errors[:20],
            "synced_sample": [
                {
                    "doc_id": r.get("doc_id"),
                    "api": r.get("api"),
                    "output_fields_count": len(r.get("output_fields") or []),
                    "sdk_valid": r.get("sdk_valid"),
                }
                for r in synced[:20]
            ],
        }



def load_specs_index() -> dict[str, dict[str, Any]]:
    """api_name -> spec row."""
    cache = load_api_specs_cache()
    out: dict[str, dict[str, Any]] = {}
    for row in cache.values():
        api = row.get("api")
        if api:
            out[str(api)] = row
    return out
