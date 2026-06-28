"""TIA preflight test — 11 checks before approval / L3 activation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd
from sqlalchemy.orm import Session

from app.catalog.tia_probe_registry import last_trading_day, resolve_probe_params
from app.core.exceptions import NotFoundError, ValidationError
from app.services.catalog.canonical_standard import (
    resolve_schema_for_ddl,
    validate_canonical_for_ddl,
)
from app.services.tia.api_probe_service import TiaApiProbeService
from app.services.tia.collect_pattern import (
    enrich_schema_collect,
    estimate_calls_for_pattern,
    resolve_collect_pattern,
    validate_collect_pattern,
)
from app.services.tia.credentials import resolve_tushare_scan_credentials
from app.services.tia.scan.probe_planner import resolve_probe_spec
from app.services.tia.scan.types import OfficialApiEntry
from app.services.tia.sync_profiles import resolve_sync_profile
from app.sync.tia_collect.router import get_collect_strategy

ProApiCaller = Callable[[str, str, dict[str, Any]], pd.DataFrame]

PREFLIGHT_CHECK_KEYS = (
    "probe_spec",
    "collect_pattern",
    "schema_ddl",
    "api_budget",
    "pattern_consistency",
    "min_points",
    "live_probe",
    "field_match",
    "collect_mode",
    "strategy_ready",
    "collect_params_parity",
)


@dataclass
class PreflightCheck:
    key: str
    label: str
    status: str  # pass | warn | fail | skip
    message: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightTestResult:
    api_name: str
    passed: bool
    checks: list[PreflightCheck]
    collect_pattern: dict[str, Any] = field(default_factory=dict)
    blocking_errors: list[str] = field(default_factory=list)
    actual_fields: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_name": self.api_name,
            "passed": self.passed,
            "checks": [asdict(c) for c in self.checks],
            "collect_pattern": self.collect_pattern,
            "blocking_errors": self.blocking_errors,
            "actual_fields": self.actual_fields,
        }

    def to_activation_step(self) -> dict[str, Any]:
        failed = [c for c in self.checks if c.status == "fail"]
        warned = [c for c in self.checks if c.status == "warn"]
        step: dict[str, Any] = {
            "status": "success" if self.passed else "failed",
            "passed": self.passed,
            "checks_passed": sum(1 for c in self.checks if c.status == "pass"),
            "checks_warned": len(warned),
            "checks_failed": len(failed),
            "blocking_errors": self.blocking_errors,
            "collect_pattern": self.collect_pattern.get("pattern"),
            "collect_mode": self.collect_pattern.get("mode"),
            "checks": [asdict(c) for c in self.checks],
        }
        if self.actual_fields:
            step["actual_fields"] = list(self.actual_fields)
        live = next((c for c in self.checks if c.key == "live_probe"), None)
        if live and live.detail.get("fields_source"):
            step["fields_source"] = live.detail["fields_source"]
        return step


_CHECK_LABELS: dict[str, str] = {
    "probe_spec": "探针规格可解析",
    "collect_pattern": "采集模式校验",
    "schema_ddl": "Schema / DDL 就绪",
    "api_budget": "API 调用预算",
    "pattern_consistency": "catalog 与探针一致性",
    "min_points": "积分门槛",
    "live_probe": "实盘探针（1 次）",
    "field_match": "字段覆盖率",
    "collect_mode": "采集模式模拟",
    "strategy_ready": "采集策略可路由",
    "collect_params_parity": "探针与采集参数一致",
}


def _narrow_probe_params(params: dict[str, Any]) -> dict[str, Any]:
    """Shrink date windows for preflight live probe."""
    out = dict(params)
    end = date.today()
    start = end - timedelta(days=5)
    if "start_date" in out or "end_date" in out:
        out["start_date"] = start.strftime("%Y%m%d")
        out["end_date"] = end.strftime("%Y%m%d")
    if "trade_date" in out:
        out["trade_date"] = last_trading_day(end).strftime("%Y%m%d")
    return out


def _wctapi_output_fields(api_name: str) -> list[str]:
    """Output field names from synced wctapi specs (fallback when no live token)."""
    from app.services.catalog.field_resolution import resolve_expected_fields
    from app.services.tia.scan.api_spec_store import get_api_spec_by_name

    spec = get_api_spec_by_name(api_name)
    if spec and spec.get("output_fields"):
        return [str(f) for f in spec["output_fields"] if f]
    return resolve_expected_fields(api_name)


class TiaPreflightTestService:
    """Run 11 preflight checks; block L3 when any check fails."""

    def __init__(self, caller: ProApiCaller | None = None) -> None:
        self._probe = TiaApiProbeService(caller=caller)

    def _apply_schema_from_field_list(
        self,
        *,
        api_name: str,
        checks: list[PreflightCheck],
        blocking: list[str],
        field_list: list[str],
        fields_source: str,
        live_probe_status: str,
        live_probe_message: str,
        field_match_message: str,
        require_live_actual: bool,
    ) -> dict[str, Any]:
        """Build schema DDL checks from live probe or wctapi doc output_fields."""
        from app.services.tia.unique_key_registry import probe_columns_cover_unique_keys

        schema = resolve_schema_for_ddl(
            api_name,
            None,
            force_rebuild=True,
            live_fields=field_list or None,
            require_live_actual=require_live_actual,
        )
        uk_ok, uk_missing = probe_columns_cover_unique_keys(schema, field_list)
        checks.append(
            PreflightCheck(
                key="live_probe",
                label=_CHECK_LABELS["live_probe"],
                status=live_probe_status,
                message=live_probe_message,
                detail={"fields_source": fields_source, "field_count": len(field_list)},
            )
        )
        if not uk_ok:
            checks.append(
                PreflightCheck(
                    key="field_match",
                    label=_CHECK_LABELS["field_match"],
                    status="fail",
                    message=f"唯一键列未在字段列表中: {', '.join(uk_missing)}",
                    detail={
                        "unique_keys": schema.get("unique_keys", []),
                        "missing_unique_keys": uk_missing,
                        "fields_source": fields_source,
                    },
                )
            )
            blocking.append(f"{api_name}: 唯一键列缺失 — {', '.join(uk_missing)}")
        else:
            checks.append(
                PreflightCheck(
                    key="field_match",
                    label=_CHECK_LABELS["field_match"],
                    status="pass",
                    message=field_match_message,
                    detail={
                        "actual_fields": field_list,
                        "unique_keys": schema.get("unique_keys", []),
                        "fields_source": fields_source,
                    },
                )
            )
        ddl_errors = validate_canonical_for_ddl(schema, api_name)
        for idx, check in enumerate(checks):
            if check.key != "schema_ddl":
                continue
            if ddl_errors:
                checks[idx] = PreflightCheck(
                    key="schema_ddl",
                    label=_CHECK_LABELS["schema_ddl"],
                    status="fail",
                    message="; ".join(ddl_errors),
                )
                blocking.extend(ddl_errors)
            else:
                checks[idx] = PreflightCheck(
                    key="schema_ddl",
                    label=_CHECK_LABELS["schema_ddl"],
                    status="pass",
                    message=(
                        f"{len(schema.get('columns', []))} 列，DDL 就绪"
                        f"（{fields_source}，{len(field_list)} 字段）"
                    ),
                    detail={
                        "unique_keys": schema.get("unique_keys", []),
                        "indexes": schema.get("indexes", []),
                        "unique_constraint": schema.get("unique_constraint"),
                        "fields_source": fields_source,
                        "field_count": len(field_list),
                    },
                )
            break
        return schema

    def run(
        self,
        session: Session | None,
        api_name: str,
        *,
        live_probe: bool = True,
    ) -> PreflightTestResult:
        checks: list[PreflightCheck] = []
        blocking: list[str] = []
        pattern_meta: dict[str, Any] = {}
        schema: dict[str, Any] | None = None
        probe_spec: dict[str, Any] | None = None
        spec_source: str | None = None
        live_fields: list[str] = []

        # 1. probe_spec
        try:
            entry = self._official_entry(api_name)
            probe_spec, spec_source, _ = resolve_probe_spec(api_name, entry)
            if not probe_spec:
                checks.append(
                    PreflightCheck(
                        key="probe_spec",
                        label=_CHECK_LABELS["probe_spec"],
                        status="fail",
                        message="无法解析探针规格",
                    )
                )
                blocking.append(f"{api_name}: 无 probe 规格")
            else:
                checks.append(
                    PreflightCheck(
                        key="probe_spec",
                        label=_CHECK_LABELS["probe_spec"],
                        status="pass",
                        message=f"来源 {spec_source}",
                        detail={"expected_fields": probe_spec.get("expected_fields", [])},
                    )
                )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    key="probe_spec",
                    label=_CHECK_LABELS["probe_spec"],
                    status="fail",
                    message=str(exc),
                )
            )
            blocking.append(str(exc))

        # 2. collect_pattern
        try:
            pattern = resolve_collect_pattern(api_name)
            validation = validate_collect_pattern(api_name)
            pattern_meta = {
                "pattern": pattern.pattern_key,
                "mode": pattern.mode,
                "label": pattern.label,
                "api_calls_hint": pattern.api_calls_hint,
                "pattern_mismatch": pattern.pattern_mismatch,
                "warnings": list(pattern.warnings),
                "estimated_calls_full_sync": pattern.estimated_calls_per_year,
            }
            if validation.blocking_errors:
                checks.append(
                    PreflightCheck(
                        key="collect_pattern",
                        label=_CHECK_LABELS["collect_pattern"],
                        status="fail",
                        message="; ".join(validation.blocking_errors),
                        detail=pattern_meta,
                    )
                )
                blocking.extend(validation.blocking_errors)
            else:
                status = "warn" if pattern.pattern_mismatch else "pass"
                msg = (
                    f"{pattern.pattern_key} → {pattern.mode}"
                    if status == "pass"
                    else f"已覆盖为 {pattern.mode}（catalog 标注不一致）"
                )
                checks.append(
                    PreflightCheck(
                        key="collect_pattern",
                        label=_CHECK_LABELS["collect_pattern"],
                        status=status,
                        message=msg,
                        detail=pattern_meta,
                    )
                )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    key="collect_pattern",
                    label=_CHECK_LABELS["collect_pattern"],
                    status="fail",
                    message=str(exc),
                )
            )
            blocking.append(str(exc))

        # 3. schema_ddl
        try:
            schema = resolve_schema_for_ddl(api_name, None, force_rebuild=True, live_fields=live_fields or None)
            schema = enrich_schema_collect(schema, api_name)
            ddl_errors = validate_canonical_for_ddl(schema, api_name)
            if ddl_errors:
                checks.append(
                    PreflightCheck(
                        key="schema_ddl",
                        label=_CHECK_LABELS["schema_ddl"],
                        status="fail",
                        message="; ".join(ddl_errors),
                    )
                )
                blocking.extend(ddl_errors)
            else:
                checks.append(
                    PreflightCheck(
                        key="schema_ddl",
                        label=_CHECK_LABELS["schema_ddl"],
                        status="pass",
                        message=f"{len(schema.get('columns', []))} 列，DDL 就绪",
                        detail={
                            "unique_keys": schema.get("unique_keys", []),
                            "indexes": schema.get("indexes", []),
                            "unique_constraint": schema.get("unique_constraint"),
                        },
                    )
                )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    key="schema_ddl",
                    label=_CHECK_LABELS["schema_ddl"],
                    status="fail",
                    message=str(exc),
                )
            )
            blocking.append(str(exc))

        profile = resolve_sync_profile(api_name, schema)

        # 4. api_budget
        try:
            from app.services.tia.collect_pattern import estimate_calls_per_run

            pattern_key = pattern_meta.get("pattern") or "generic"
            est_full = estimate_calls_for_pattern(pattern_key) or 1
            est_run = estimate_calls_per_run(
                pattern_key,
                max_codes_per_run=profile.max_codes_per_run,
                max_api_calls_per_run=profile.max_api_calls_per_run,
            )
            budget = profile.max_api_calls_per_run
            if est_run > budget:
                msg = f"预估单次 {est_run} 次 > 预算 {budget}"
                checks.append(
                    PreflightCheck(
                        key="api_budget",
                        label=_CHECK_LABELS["api_budget"],
                        status="fail",
                        message=msg,
                        detail={
                            "estimated_per_run": est_run,
                            "estimated_full_sync": est_full,
                            "budget": budget,
                        },
                    )
                )
                blocking.append(f"{api_name}: {msg}")
            else:
                checks.append(
                    PreflightCheck(
                        key="api_budget",
                        label=_CHECK_LABELS["api_budget"],
                        status="pass",
                        message=(
                            f"单次 {est_run} 次 ≤ 预算 {budget}"
                            + (f"（全量约 {est_full} 次，分 chunk 回填）" if est_full > est_run else "")
                        ),
                        detail={
                            "estimated_per_run": est_run,
                            "estimated_full_sync": est_full,
                            "budget": budget,
                        },
                    )
                )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    key="api_budget",
                    label=_CHECK_LABELS["api_budget"],
                    status="fail",
                    message=str(exc),
                )
            )
            blocking.append(str(exc))

        # 5. pattern_consistency
        try:
            if pattern_meta.get("pattern_mismatch"):
                checks.append(
                    PreflightCheck(
                        key="pattern_consistency",
                        label=_CHECK_LABELS["pattern_consistency"],
                        status="warn",
                        message="catalog probe_category 与探针参数形态不一致（已自动纠偏）",
                        detail={"warnings": pattern_meta.get("warnings", [])},
                    )
                )
            else:
                checks.append(
                    PreflightCheck(
                        key="pattern_consistency",
                        label=_CHECK_LABELS["pattern_consistency"],
                        status="pass",
                        message="catalog 与探针一致",
                    )
                )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    key="pattern_consistency",
                    label=_CHECK_LABELS["pattern_consistency"],
                    status="fail",
                    message=str(exc),
                )
            )

        # 6. min_points
        creds: dict[str, Any] = {}
        if session is not None:
            creds = self._resolve_preflight_credentials(session, api_name)
        account_pts = int(creds.get("account_points") or 0)
        min_pts = self._min_points(api_name)
        from_data_source = bool(creds.get("from_data_source"))
        is_tdx = self._is_tdx_api(api_name)
        if is_tdx or not min_pts:
            checks.append(
                PreflightCheck(
                    key="min_points",
                    label=_CHECK_LABELS["min_points"],
                    status="pass",
                    message="TDX 接口无积分门槛" if is_tdx else f"积分 OK（要求 {min_pts or '—'}）",
                )
            )
        elif min_pts and account_pts and account_pts < min_pts:
            status = "fail" if from_data_source else "warn"
            msg = f"账户积分 {account_pts} < 接口要求 {min_pts}"
            checks.append(
                PreflightCheck(
                    key="min_points",
                    label=_CHECK_LABELS["min_points"],
                    status=status,
                    message=msg,
                    detail={"account_points": account_pts, "min_points": min_pts},
                )
            )
            if status == "fail":
                blocking.append(f"{api_name}: 积分不足（需 {min_pts}）")
        elif min_pts and not account_pts:
            checks.append(
                PreflightCheck(
                    key="min_points",
                    label=_CHECK_LABELS["min_points"],
                    status="skip",
                    message="未配置积分，跳过校验",
                )
            )
        else:
            checks.append(
                PreflightCheck(
                    key="min_points",
                    label=_CHECK_LABELS["min_points"],
                    status="pass",
                    message=f"积分 OK（账户 {account_pts or '—'} / 要求 {min_pts or '—'}）",
                )
            )

        # 7–8. live_probe + field_match
        probe_row: dict[str, Any] | None = None
        if live_probe and probe_spec and session is not None:
            if is_tdx:
                schema = self._run_tdx_live_probe(
                    api_name=api_name,
                    probe_spec=probe_spec,
                    creds=creds,
                    checks=checks,
                    blocking=blocking,
                )
                if schema:
                    live_fields = [
                        str(col.get("key"))
                        for col in schema.get("columns", [])
                        if col.get("key")
                    ]
            else:
                token = creds.get("token")
                entry = self._official_entry(api_name)
                if not token:
                    doc_fields = _wctapi_output_fields(api_name)
                    if not doc_fields:
                        from app.services.catalog.field_resolution import resolve_expected_fields

                        doc_fields = resolve_expected_fields(api_name)
                    if doc_fields:
                        live_fields = list(doc_fields)
                        schema = self._apply_schema_from_field_list(
                            api_name=api_name,
                            checks=checks,
                            blocking=blocking,
                            field_list=live_fields,
                            fields_source="wctapi_md",
                            live_probe_status="warn",
                            live_probe_message=(
                                f"无 Token，使用文档/注册表 {len(live_fields)} 列出参建表"
                            ),
                            field_match_message=(
                                f"注册表 {len(live_fields)} 列，唯一键校验通过"
                            ),
                            require_live_actual=False,
                        )
                    else:
                        checks.append(
                            PreflightCheck(
                                key="live_probe",
                                label=_CHECK_LABELS["live_probe"],
                                status="fail",
                                message="无 Token 且无 wctapi 出参，无法建表",
                            )
                        )
                        blocking.append(f"{api_name}: 无 Token，无法实盘探针且无文档出参")
                        checks.append(
                            PreflightCheck(
                                key="field_match",
                                label=_CHECK_LABELS["field_match"],
                                status="fail",
                                message="依赖实盘探针或 wctapi 出参",
                            )
                        )
                else:
                    narrow_params = _narrow_probe_params(
                        resolve_probe_params(dict(probe_spec.get("params") or {}))
                    )
                    narrow_spec = {**probe_spec, "params": narrow_params}
                    try:
                        result = self._probe._probe_one(
                            api_name,
                            probe_spec=narrow_spec,
                            spec_source=spec_source,
                            official_entry=entry,
                            min_points_override=min_pts,
                            token=token,
                            account_points=account_pts or min_pts or 120,
                            max_calls_per_minute=creds.get("max_calls_per_minute"),
                        )
                        probe_row = result.to_dict()
                        if result.status == "ok":
                            live_fields = list(result.actual_fields or [])
                            checks.append(
                                PreflightCheck(
                                    key="live_probe",
                                    label=_CHECK_LABELS["live_probe"],
                                    status="pass",
                                    message=f"返回 {result.rows} 行",
                                    detail={"latency_ms": result.latency_ms},
                                )
                            )
                            schema = resolve_schema_for_ddl(
                                api_name,
                                None,
                                force_rebuild=True,
                                live_fields=live_fields or None,
                                require_live_actual=True,
                            )
                            missing = result.missing_fields
                            extra = result.extra_fields
                            from app.services.tia.unique_key_registry import (
                                probe_columns_cover_unique_keys,
                            )

                            uk_ok, uk_missing = probe_columns_cover_unique_keys(
                                schema,
                                list(result.actual_fields or []),
                            )
                            if not uk_ok:
                                checks.append(
                                    PreflightCheck(
                                        key="field_match",
                                        label=_CHECK_LABELS["field_match"],
                                        status="fail",
                                        message=f"唯一键列未在探针返回: {', '.join(uk_missing)}",
                                        detail={
                                            "unique_keys": schema.get("unique_keys", []),
                                            "missing_unique_keys": uk_missing,
                                        },
                                    )
                                )
                                blocking.append(
                                    f"{api_name}: 唯一键列未返回 — {', '.join(uk_missing)}"
                                )
                            elif missing:
                                checks.append(
                                    PreflightCheck(
                                        key="field_match",
                                        label=_CHECK_LABELS["field_match"],
                                        status="pass",
                                        message=(
                                            f"实盘 {len(live_fields)} 列；文档缺 "
                                            f"{len(missing)} 列（以实盘为准）"
                                        ),
                                        detail={
                                            "actual_fields": live_fields,
                                            "missing_in_doc": missing,
                                            "extra_vs_doc": extra,
                                            "unique_keys": schema.get("unique_keys", []),
                                        },
                                    )
                                )
                            elif extra:
                                checks.append(
                                    PreflightCheck(
                                        key="field_match",
                                        label=_CHECK_LABELS["field_match"],
                                        status="pass",
                                        message=(
                                            f"实盘 {len(live_fields)} 列；较文档多 "
                                            f"{len(extra)} 列（以实盘为准）"
                                        ),
                                        detail={
                                            "unique_keys": schema.get("unique_keys", []),
                                            "extra_vs_doc": extra,
                                            "actual_fields": live_fields,
                                        },
                                    )
                                )
                            else:
                                checks.append(
                                    PreflightCheck(
                                        key="field_match",
                                        label=_CHECK_LABELS["field_match"],
                                        status="pass",
                                        message=f"实盘 {len(live_fields)} 列，与文档一致",
                                        detail={
                                            "unique_keys": schema.get("unique_keys", []),
                                            "actual_fields": live_fields,
                                        },
                                    )
                                )
                            ddl_errors = validate_canonical_for_ddl(schema, api_name)
                            for idx, check in enumerate(checks):
                                if check.key != "schema_ddl":
                                    continue
                                if ddl_errors:
                                    checks[idx] = PreflightCheck(
                                        key="schema_ddl",
                                        label=_CHECK_LABELS["schema_ddl"],
                                        status="fail",
                                        message="; ".join(ddl_errors),
                                    )
                                    blocking.extend(ddl_errors)
                                else:
                                    checks[idx] = PreflightCheck(
                                        key="schema_ddl",
                                        label=_CHECK_LABELS["schema_ddl"],
                                        status="pass",
                                        message=(
                                            f"{len(schema.get('columns', []))} 列，"
                                            "DDL 就绪（含实盘字段）"
                                        ),
                                        detail={
                                            "unique_keys": schema.get("unique_keys", []),
                                            "indexes": schema.get("indexes", []),
                                            "unique_constraint": schema.get("unique_constraint"),
                                            "live_field_count": len(live_fields),
                                        },
                                    )
                                break
                        else:
                            doc_fields = _wctapi_output_fields(api_name)
                            if doc_fields:
                                live_fields = list(doc_fields)
                                schema = self._apply_schema_from_field_list(
                                    api_name=api_name,
                                    checks=checks,
                                    blocking=blocking,
                                    field_list=live_fields,
                                    fields_source="wctapi_md",
                                    live_probe_status="warn",
                                    live_probe_message=(
                                        f"实盘探针未返回列（{result.message or result.status}），"
                                        f"使用 wctapi 文档 {len(live_fields)} 列建表"
                                    ),
                                    field_match_message=(
                                        f"wctapi 文档 {len(live_fields)} 列，唯一键校验通过"
                                    ),
                                    require_live_actual=False,
                                )
                            else:
                                checks.append(
                                    PreflightCheck(
                                        key="live_probe",
                                        label=_CHECK_LABELS["live_probe"],
                                        status="fail",
                                        message=result.message or result.status,
                                        detail=probe_row,
                                    )
                                )
                                blocking.append(f"{api_name}: 实盘探针失败 — {result.message}")
                                checks.append(
                                    PreflightCheck(
                                        key="field_match",
                                        label=_CHECK_LABELS["field_match"],
                                        status="skip",
                                        message="探针未成功",
                                    )
                                )
                    except Exception as exc:
                        doc_fields = _wctapi_output_fields(api_name)
                        if doc_fields:
                            live_fields = list(doc_fields)
                            schema = self._apply_schema_from_field_list(
                                api_name=api_name,
                                checks=checks,
                                blocking=blocking,
                                field_list=live_fields,
                                fields_source="wctapi_md",
                                live_probe_status="warn",
                                live_probe_message=(
                                    f"实盘探针异常（{exc}），"
                                    f"使用 wctapi 文档 {len(live_fields)} 列建表"
                                ),
                                field_match_message=(
                                    f"wctapi 文档 {len(live_fields)} 列，唯一键校验通过"
                                ),
                                require_live_actual=False,
                            )
                        else:
                            checks.append(
                                PreflightCheck(
                                    key="live_probe",
                                    label=_CHECK_LABELS["live_probe"],
                                    status="fail",
                                    message=str(exc),
                                )
                            )
                            blocking.append(str(exc))
                            checks.append(
                                PreflightCheck(
                                    key="field_match",
                                    label=_CHECK_LABELS["field_match"],
                                    status="skip",
                                    message="探针异常",
                                )
                            )
        else:
            checks.append(
                PreflightCheck(
                    key="live_probe",
                    label=_CHECK_LABELS["live_probe"],
                    status="skip",
                    message="未启用或无 session",
                )
            )
            checks.append(
                PreflightCheck(
                    key="field_match",
                    label=_CHECK_LABELS["field_match"],
                    status="skip",
                    message="未启用或无 session",
                )
            )

        # 9. collect_mode
        try:
            mode = profile.mode
            est = estimate_calls_for_pattern(pattern_meta.get("pattern", "generic")) or 1
            checks.append(
                PreflightCheck(
                    key="collect_mode",
                    label=_CHECK_LABELS["collect_mode"],
                    status="pass",
                    message=f"mode={mode}，预估 {est} 次/全量",
                    detail={"mode": mode, "schedule_cron": profile.schedule_cron},
                )
            )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    key="collect_mode",
                    label=_CHECK_LABELS["collect_mode"],
                    status="fail",
                    message=str(exc),
                )
            )
            blocking.append(str(exc))

        # 10. strategy_ready
        try:
            strategy = get_collect_strategy(profile.mode)
            checks.append(
                PreflightCheck(
                    key="strategy_ready",
                    label=_CHECK_LABELS["strategy_ready"],
                    status="pass",
                    message=f"{profile.mode} → {type(strategy).__name__}",
                )
            )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    key="strategy_ready",
                    label=_CHECK_LABELS["strategy_ready"],
                    status="fail",
                    message=str(exc),
                )
            )
            blocking.append(str(exc))

        # 11. collect_params_parity — preflight probe vs runtime collect base params
        try:
            from app.sync.tia_collect.params import (
                SNAPSHOT_FULL_MARKET_PARAMS,
                resolve_collect_params,
                sanitize_collect_params,
            )

            if probe_spec and schema:
                runtime_base = sanitize_collect_params(
                    resolve_collect_params(api_name, schema)
                )
                if api_name in SNAPSHOT_FULL_MARKET_PARAMS:
                    preflight_base = runtime_base
                else:
                    preflight_base = sanitize_collect_params(
                        resolve_probe_params(dict(probe_spec.get("params") or {}))
                    )
                iter_keys = frozenset(
                    {"ts_code", "start_date", "end_date", "trade_date", "period"}
                )
                pre_stable = {k: v for k, v in preflight_base.items() if k not in iter_keys}
                run_stable = {k: v for k, v in runtime_base.items() if k not in iter_keys}
                if pre_stable != run_stable:
                    checks.append(
                        PreflightCheck(
                            key="collect_params_parity",
                            label=_CHECK_LABELS["collect_params_parity"],
                            status="fail",
                            message=f"探针 {pre_stable} ≠ 采集 {run_stable}",
                            detail={
                                "preflight_params": preflight_base,
                                "runtime_params": runtime_base,
                            },
                        )
                    )
                    blocking.append(
                        f"{api_name}: 探针与采集参数不一致 — pre={pre_stable} collect={run_stable}"
                    )
                else:
                    checks.append(
                        PreflightCheck(
                            key="collect_params_parity",
                            label=_CHECK_LABELS["collect_params_parity"],
                            status="pass",
                            message="探针与采集基础参数一致",
                            detail={
                                "preflight_params": preflight_base,
                                "runtime_params": runtime_base,
                            },
                        )
                    )
            else:
                checks.append(
                    PreflightCheck(
                        key="collect_params_parity",
                        label=_CHECK_LABELS["collect_params_parity"],
                        status="skip",
                        message="无 probe_spec 或 schema",
                    )
                )
        except Exception as exc:
            checks.append(
                PreflightCheck(
                    key="collect_params_parity",
                    label=_CHECK_LABELS["collect_params_parity"],
                    status="fail",
                    message=str(exc),
                )
            )
            blocking.append(str(exc))

        passed = not blocking and not any(c.status == "fail" for c in checks)
        return PreflightTestResult(
            api_name=api_name,
            passed=passed,
            checks=checks,
            collect_pattern=pattern_meta,
            blocking_errors=blocking,
            actual_fields=live_fields,
        )

    @staticmethod
    def _is_tdx_api(api_name: str) -> bool:
        from app.services.tia.scan.index_loader import load_bundled_index

        bundled = load_bundled_index("tdx")
        return api_name in {entry.api for entry in bundled.apis}

    @staticmethod
    def _resolve_preflight_credentials(session: Session, api_name: str) -> dict[str, Any]:
        if TiaPreflightTestService._is_tdx_api(api_name):
            from app.services.tia.credentials_tdx import resolve_tdx_collect_credentials

            try:
                return resolve_tdx_collect_credentials(session, None)
            except (NotFoundError, ValidationError):
                return {"provider": "tdx", "note": "TDX Sidecar credentials not configured"}
        try:
            return resolve_tushare_scan_credentials(session)
        except (NotFoundError, ValidationError):
            return {}

    def _run_tdx_live_probe(
        self,
        *,
        api_name: str,
        probe_spec: dict[str, Any],
        creds: dict[str, Any],
        checks: list[PreflightCheck],
        blocking: list[str],
    ) -> dict[str, Any] | None:
        from app.services.catalog.field_resolution import resolve_expected_fields
        from app.services.collectors.tdx_sidecar import TdxSidecarClient

        expected = list(probe_spec.get("expected_fields") or [])
        if not expected:
            expected = resolve_expected_fields(api_name)
        base_url = (creds.get("base_url") or "").strip()
        live_fields: list[str] = []
        fields_source = "tdx_registry"
        live_status = "warn"
        live_message = "未配置 Sidecar，使用注册表字段建表"

        if base_url:
            try:
                client = TdxSidecarClient(base_url, creds.get("api_token"))
                health = client.health()
                if not health.get("ok", True):
                    live_message = str(health.get("message") or "Sidecar health failed")
                elif api_name.startswith("concept"):
                    from app.catalog.tia_probe_registry import last_trading_day

                    catalog = client.concept_catalog(
                        last_trading_day(),
                        install_root=creds.get("install_root"),
                        paths=creds.get("paths"),
                    )
                    rows = catalog.get("indices") or catalog.get("members") or []
                    if rows and isinstance(rows[0], dict):
                        live_fields = list(rows[0].keys())
                        fields_source = "tdx_sidecar_concept"
                        live_status = "pass"
                        live_message = f"Sidecar concept-catalog 返回 {len(rows)} 行"
                    else:
                        live_fields = list(expected)
                        live_message = "Sidecar OK，concept-catalog 无样本，使用注册表字段"
                else:
                    live_fields = list(expected)
                    fields_source = "tdx_sidecar_health"
                    live_status = "pass"
                    live_message = "Sidecar health OK"
            except Exception as exc:
                live_fields = list(expected)
                live_message = f"Sidecar 探针异常（{exc}），使用注册表字段"
        else:
            live_fields = list(expected)

        if not live_fields:
            checks.append(
                PreflightCheck(
                    key="live_probe",
                    label=_CHECK_LABELS["live_probe"],
                    status="fail",
                    message="无 Sidecar 且无注册表出参",
                )
            )
            blocking.append(f"{api_name}: 无法解析 TDX 字段")
            checks.append(
                PreflightCheck(
                    key="field_match",
                    label=_CHECK_LABELS["field_match"],
                    status="fail",
                    message="无可用字段",
                )
            )
            return None

        return self._apply_schema_from_field_list(
            api_name=api_name,
            checks=checks,
            blocking=blocking,
            field_list=live_fields,
            fields_source=fields_source,
            live_probe_status=live_status,
            live_probe_message=live_message,
            field_match_message=f"TDX {len(live_fields)} 列，唯一键校验通过",
            require_live_actual=False,
        )

    @staticmethod
    def _official_entry(api_name: str) -> OfficialApiEntry | None:
        from app.services.tia.collect_pattern import _official_entry_for_api

        return _official_entry_for_api(api_name)

    @staticmethod
    def _min_points(api_name: str) -> int | None:
        from app.catalog.tia_probe_registry import api_probe_meta
        from app.services.tushare.quota import api_min_points

        meta = api_probe_meta(api_name) or {}
        if meta.get("min_points") is not None:
            return int(meta["min_points"])
        entry = TiaPreflightTestService._official_entry(api_name)
        if entry and entry.min_points is not None:
            return int(entry.min_points)
        try:
            return api_min_points(api_name)
        except Exception:
            return None


def run_preflight_or_raise(session: Session, api_name: str, *, live_probe: bool = True) -> PreflightTestResult:
    """Run preflight; raise ValidationError when checks fail."""
    result = TiaPreflightTestService().run(session, api_name, live_probe=live_probe)
    if not result.passed:
        raise ValidationError(
            "Preflight 测试未通过: " + "; ".join(result.blocking_errors or ["存在失败项"])
        )
    return result
