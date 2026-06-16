"""Iter-10 audit: preflight probe params vs runtime collect params."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.catalog.tia_probe_registry import resolve_probe_params
from app.services.catalog.canonical_standard import build_canonical_schema
from app.services.tia.collect_pattern import (
    resolve_collect_pattern,
    resolve_probe_params_for_api,
)
from app.services.tia.scan.probe_planner import resolve_probe_spec
from app.services.tia.scan.tushare_doc_registry import load_api_by_doc_id
from app.services.tia.sync_profiles import resolve_sync_profile
from app.sync.tia_collect.params import resolve_collect_params, sanitize_collect_params


@dataclass
class AuditFinding:
    api_name: str
    severity: str  # critical | high | medium | low
    category: str
    message: str
    preflight_params: dict[str, Any] = field(default_factory=dict)
    collect_params: dict[str, Any] = field(default_factory=dict)
    strategy_params: dict[str, Any] = field(default_factory=dict)
    mode: str = ""


def _load_stock_apis() -> list[str]:
    path = (
        Path(__file__).resolve().parents[2]
        / "catalog/providers/tushare_stock_official_apis.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    return sorted({a["api"] for a in data.get("apis", []) if a.get("api")})


def _all_catalog_apis() -> list[str]:
    seen: set[str] = set()
    apis: list[str] = []
    for row in load_api_by_doc_id().values():
        api = row.get("api")
        if api and api not in seen:
            seen.add(api)
            apis.append(api)
    return sorted(apis)


def audit_api(api_name: str) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    pattern = resolve_collect_pattern(api_name)
    profile = resolve_sync_profile(api_name)
    mode = profile.mode

    spec, _, _ = resolve_probe_spec(api_name)
    preflight = sanitize_collect_params(
        resolve_probe_params(dict((spec or {}).get("params") or {}))
    )
    collect_empty = resolve_probe_params_for_api(api_name, {})
    strategy_params = resolve_collect_params(api_name, {})

    # 1. Preflight vs collect (empty schema) divergence
    if preflight != collect_empty:
        sev = "critical" if mode in ("snapshot", "generic", "exchange_date_range") else "high"
        findings.append(
            AuditFinding(
                api_name=api_name,
                severity=sev,
                category="preflight_vs_collect_empty_schema",
                message=f"探针参数 {preflight} ≠ 采集参数 {collect_empty}",
                preflight_params=preflight,
                collect_params=collect_empty,
                mode=mode,
            )
        )

    # 2. Schema missing probe_params after build_canonical_schema
    try:
        schema = build_canonical_schema(
            api_name,
            live_fields=(spec or {}).get("expected_fields") or ["ts_code"],
        )
        if not schema.get("probe_params") and preflight:
            findings.append(
                AuditFinding(
                    api_name=api_name,
                    severity="medium",
                    category="schema_missing_probe_params",
                    message="L3 schema 未持久化 probe_params",
                    preflight_params=preflight,
                    mode=mode,
                )
            )
    except Exception:
        pass

    # 3. Iteration strategies vs unified collect params
    if mode in ("date_range", "trade_date", "ts_code", "period"):
        if preflight and strategy_params != preflight:
            extra_preflight = {
                k: v
                for k, v in preflight.items()
                if k not in ("ts_code", "start_date", "end_date", "trade_date", "period")
            }
            if extra_preflight:
                findings.append(
                    AuditFinding(
                        api_name=api_name,
                        severity="high",
                        category="strategy_ignores_probe_template",
                        message=(
                            f"{mode} 策略参数 {strategy_params}，"
                            f"丢失模板键 {extra_preflight}"
                        ),
                        preflight_params=preflight,
                        strategy_params=strategy_params,
                        mode=mode,
                    )
                )

    # 4. list_limit probe limit leaks into collect
    if "limit" in collect_empty and mode == "snapshot":
        findings.append(
            AuditFinding(
                api_name=api_name,
                severity="critical",
                category="probe_limit_in_collect",
                message=f"采集将带 limit={collect_empty['limit']}，全量快照会被截断",
                preflight_params=preflight,
                collect_params=collect_empty,
                mode=mode,
            )
        )

    # 5. SSE-only fallback
    if collect_empty == {"exchange": "SSE"} and preflight != {"exchange": "SSE"}:
        findings.append(
            AuditFinding(
                api_name=api_name,
                severity="critical",
                category="sse_fallback",
                message="采集回退 exchange=SSE，与探针不一致",
                preflight_params=preflight,
                collect_params=collect_empty,
                mode=mode,
            )
        )

    # 6. list_basic missing list_status
    if (spec or {}).get("params", {}).get("list_status") and "list_status" not in collect_empty:
        if mode == "snapshot":
            findings.append(
                AuditFinding(
                    api_name=api_name,
                    severity="high",
                    category="missing_list_status",
                    message="list_basic 采集缺少 list_status",
                    preflight_params=preflight,
                    collect_params=collect_empty,
                    mode=mode,
                )
            )

    return findings


def run_audit(scope: str = "stock_a") -> dict[str, Any]:
    apis = _load_stock_apis() if scope == "stock_a" else _all_catalog_apis()
    all_findings: list[AuditFinding] = []
    for api in apis:
        all_findings.extend(audit_api(api))

    by_severity: dict[str, list[dict]] = {"critical": [], "high": [], "medium": [], "low": []}
    for f in all_findings:
        by_severity[f.severity].append(
            {
                "api": f.api_name,
                "category": f.category,
                "mode": f.mode,
                "message": f.message,
                "preflight": f.preflight_params,
                "collect": f.collect_params,
                "strategy": f.strategy_params,
            }
        )

    return {
        "scope": scope,
        "apis_scanned": len(apis),
        "finding_count": len(all_findings),
        "by_severity": by_severity,
    }
