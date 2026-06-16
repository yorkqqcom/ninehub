"""TIA scan: live Tushare API probe vs catalog documentation fields."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import pandas as pd

from app.catalog.tia_probe_registry import resolve_probe_params
from app.services.collectors.tushare import wait_before_pro_call
from app.services.tia.scan.probe_planner import resolve_probe_spec
from app.services.tia.scan.tushare_doc_registry import (
    build_doc_page_url,
    resolve_api_meta,
    resolve_canonical_api_meta,
    resolve_min_points_for_doc_id,
)
from app.services.tia.scan.types import OfficialApiEntry
from app.services.tushare.pro_response import ProApiResult, call_pro_api_raw, parse_permission_info
from app.services.tushare.quota import api_min_points

ProApiCaller = Callable[[str, str, dict[str, Any]], pd.DataFrame]
RawProApiCaller = Callable[[str, str, dict[str, Any], int | None], ProApiResult]
ProbeProgressCallback = Callable[[str, dict[str, Any], int, int], None]

def _local_catalog_min_points(api_name: str) -> int | None:
    from app.catalog.tia_probe_registry import OFFICIAL_ONLY_API_PROBES

    explicit = OFFICIAL_ONLY_API_PROBES.get(api_name) or {}
    if explicit.get("min_points") is not None:
        return int(explicit["min_points"])
    canonical = resolve_canonical_api_meta(api_name) or {}
    if canonical.get("min_points") is not None:
        return int(canonical["min_points"])
    return None


@dataclass
class ApiProbeResult:
    api: str
    status: str
    doc_id: int | None = None
    doc_url: str | None = None
    catalog_min_points: int | None = None
    official_doc_min_points: int | None = None
    api_live_min_points: int | None = None
    interface_level: int | None = None
    min_points_source: str | None = None
    api_error_code: int | None = None
    account_points: int | None = None
    rows: int = 0
    expected_fields: list[str] = field(default_factory=list)
    actual_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    extra_fields: list[str] = field(default_factory=list)
    doc_consistent: bool | None = None
    points_doc_mismatch: bool = False
    probe_params: dict[str, Any] = field(default_factory=dict)
    probe_spec_source: str | None = None
    latency_ms: int | None = None
    probe_source: str = "catalog"
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def refresh_points_mismatch(self) -> None:
        catalog_pts = self.catalog_min_points
        if catalog_pts is None:
            catalog_pts = api_min_points(self.api)
        refs = [
            int(v)
            for v in (catalog_pts, self.official_doc_min_points, self.api_live_min_points)
            if v is not None
        ]
        self.points_doc_mismatch = len(refs) >= 2 and len(set(refs)) > 1

def default_pro_api_caller(
    token: str,
    api_name: str,
    params: dict[str, Any],
    *,
    max_calls_per_minute: int | None = None,
) -> pd.DataFrame:
    wait_before_pro_call(max_calls_per_minute)
    import tushare as ts

    pro = ts.pro_api(token)
    df = getattr(pro, api_name)(**params)
    return df if df is not None else pd.DataFrame()


def default_raw_pro_api_caller(
    token: str,
    api_name: str,
    params: dict[str, Any],
    max_calls_per_minute: int | None,
) -> ProApiResult:
    return call_pro_api_raw(
        token,
        api_name,
        params,
        max_calls_per_minute=max_calls_per_minute,
    )


class TiaApiProbeService:
    def __init__(
        self,
        caller: ProApiCaller | None = None,
        raw_caller: RawProApiCaller | None = None,
    ) -> None:
        self._caller = caller
        self._raw_caller = raw_caller
    def probe_catalog_apis(
        self,
        api_names: list[str],
        *,
        token: str | None,
        account_points: int,
        max_calls_per_minute: int | None = None,
        official_map: dict[str, OfficialApiEntry] | None = None,
        override_points: dict[str, int] | None = None,
        on_progress: ProbeProgressCallback | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        official_map = official_map or {}
        total = len(api_names)
        for idx, api in enumerate(api_names, start=1):
            entry = official_map.get(api)
            probe_spec, spec_source, min_pts = resolve_probe_spec(api, entry)
            if not probe_spec:
                row = ApiProbeResult(
                    api=api,
                    status="skipped_no_probe",
                    message="未配置 probe 规格",
                ).to_dict()
            else:
                row = self._probe_one(
                    api,
                    probe_spec=probe_spec,
                    spec_source=spec_source,
                    official_entry=entry,
                    min_points_override=min_pts,
                    token=token,
                    account_points=account_points,
                    max_calls_per_minute=max_calls_per_minute,
                    override_points=override_points,
                ).to_dict()
            results.append(row)
            if on_progress:
                on_progress(api, row, idx, total)
        return results

    def _call_raw(
        self,
        token: str,
        api_name: str,
        params: dict[str, Any],
        max_calls_per_minute: int | None,
    ) -> ProApiResult:
        if self._raw_caller is not None:
            return self._raw_caller(token, api_name, params, max_calls_per_minute)
        if self._caller is not None:
            try:
                df = self._caller(token, api_name, params)
                return ProApiResult(
                    api_name=api_name,
                    ok=True,
                    code=0,
                    df=df if df is not None else pd.DataFrame(),
                )
            except Exception as exc:
                return ProApiResult(
                    api_name=api_name,
                    ok=False,
                    msg=str(exc),
                    raw={"msg": str(exc)},
                )
        return default_raw_pro_api_caller(token, api_name, params, max_calls_per_minute)

    def _apply_permission_meta(
        self,
        base: ApiProbeResult,
        perm: dict[str, Any],
    ) -> None:
        base.api_live_min_points = perm.get("api_live_min_points")
        base.interface_level = perm.get("interface_level")
        base.min_points_source = perm.get("min_points_source")
        base.api_error_code = perm.get("api_error_code")
        base.refresh_points_mismatch()
    def _probe_one(
        self,
        api_name: str,
        *,
        probe_spec: dict[str, Any],
        spec_source: str | None,
        official_entry: OfficialApiEntry | None,
        min_points_override: int | None,
        token: str | None,
        account_points: int,
        max_calls_per_minute: int | None,
        override_points: dict[str, int] | None = None,
    ) -> ApiProbeResult:
        doc_id = official_entry.doc_id if official_entry else None
        if doc_id is None:
            canonical = resolve_canonical_api_meta(api_name) or resolve_api_meta(api_name) or {}
            doc_id = canonical.get("doc_id")
        doc_url = build_doc_page_url(doc_id) if doc_id else None

        official_doc_pts: int | None = None
        if doc_id is not None:
            resolved_pts, _ = resolve_min_points_for_doc_id(int(doc_id))
            if resolved_pts is not None:
                official_doc_pts = int(resolved_pts)
        if official_doc_pts is None and official_entry and official_entry.min_points is not None:
            official_doc_pts = int(official_entry.min_points)

        if override_points and api_name in override_points:
            catalog_pts = int(override_points[api_name])
        else:
            catalog_pts = _local_catalog_min_points(api_name)

        expected_fields: list[str] = list(probe_spec.get("expected_fields") or [])
        raw_params: dict[str, Any] = dict(probe_spec.get("params") or {})
        from app.sync.tia_collect.params import sanitize_collect_params

        params = sanitize_collect_params(resolve_probe_params(raw_params))

        if spec_source and spec_source.startswith("template:"):
            probe_source = "template"
        elif (resolve_api_meta(api_name) or {}).get("source") == "official_only":
            probe_source = "official_only"
        else:
            probe_source = "doc_registry"

        base = ApiProbeResult(
            api=api_name,
            status="pending",
            doc_id=doc_id,
            doc_url=doc_url,
            catalog_min_points=catalog_pts,
            official_doc_min_points=official_doc_pts,
            account_points=account_points,
            expected_fields=expected_fields,
            probe_params=params,
            probe_spec_source=spec_source,
            probe_source=probe_source,
        )
        base.refresh_points_mismatch()

        if not token:
            base.status = "skipped_no_token"
            base.message = "未配置 Tushare token，请在数据源或环境变量中设置"
            return base

        started = time.monotonic()
        try:
            result = self._call_raw(token, api_name, params, max_calls_per_minute)
        except ImportError:
            base.status = "skipped_no_sdk"
            base.message = "tushare SDK 未安装"
            return base
        except Exception as exc:
            perm = parse_permission_info({"msg": str(exc), "code": None, "data": None})
            if perm["is_permission_error"]:
                base.status = "failed_points"
                base.message = str(exc)
                self._apply_permission_meta(base, perm)
                return base
            base.status = "failed"
            base.message = str(exc)
            return base
        finally:
            base.latency_ms = int((time.monotonic() - started) * 1000)

        if not result.ok:
            perm = parse_permission_info(result)
            if perm["is_permission_error"]:
                base.status = "failed_points"
                self._apply_permission_meta(base, perm)
                if base.api_live_min_points is not None:
                    level_note = (
                        f"（等级 {base.interface_level}）"
                        if base.interface_level
                        and base.interface_level != base.api_live_min_points
                        else ""
                    )
                    base.message = (
                        f"接口需 {base.api_live_min_points} 积分{level_note}，"
                        f"当前账户 {account_points} 积分"
                    )
                else:
                    base.message = result.msg or "积分/权限不足"
                return base
            base.status = "failed"
            base.message = result.msg or "接口调用失败"
            base.api_error_code = result.code
            return base

        df = result.df
        if df is None or df.empty:
            base.status = "failed_empty"
            base.message = "接口返回空数据（可能为非交易日或参数无匹配）"
            base.rows = 0
            base.doc_consistent = False
            return base

        actual = [str(c) for c in df.columns.tolist()]
        missing = [f for f in expected_fields if f not in actual]
        extra = [f for f in actual if f not in expected_fields]

        base.status = "ok"
        if expected_fields:
            base.doc_consistent = len(missing) == 0
        else:
            base.doc_consistent = True

        base.rows = len(df)
        base.actual_fields = actual
        base.missing_fields = missing
        base.extra_fields = extra
        if missing:
            base.message = (
                f"探测成功，{len(df)} 行；文档缺 {len(missing)} 列（以实盘为准）"
            )
        elif extra:
            base.message = f"探测成功，{len(df)} 行；较文档多 {len(extra)} 列"
        else:
            base.message = f"探测成功，{len(df)} 行，字段与文档一致"
        return base

    @staticmethod
    def summarize(probes: list[dict[str, Any]]) -> dict[str, int]:
        summary = {
            "ok": 0,
            "doc_field_mismatch": 0,
            "failed": 0,
            "skipped": 0,
            "points_doc_mismatch": 0,
            "api_live_min_points": 0,
            "total": len(probes),
        }
        for p in probes:
            status = p.get("status", "")
            if status == "ok":
                summary["ok"] += 1
            elif status == "doc_field_mismatch":
                summary["doc_field_mismatch"] += 1
            elif status.startswith("failed"):
                summary["failed"] += 1
            else:
                summary["skipped"] += 1
            if p.get("points_doc_mismatch"):
                summary["points_doc_mismatch"] += 1
            if p.get("api_live_min_points") is not None:
                summary["api_live_min_points"] += 1
        return summary