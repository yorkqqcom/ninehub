"""Inspect installed tushare SDK and live-probe API support via Python calls."""

from __future__ import annotations

import inspect
import json
import re
import sys
from collections import Counter
from pathlib import Path

import tushare as ts

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings
from app.services.tia.scan.document2_index_builder import build_document2_official_index
from app.services.tushare.pro_response import call_pro_api_raw, parse_permission_info
from app.services.tia.scan.probe_planner import resolve_probe_spec
from app.services.tia.scan.types import OfficialApiEntry


def _hardcoded_pro_bar_apis() -> list[str]:
    apis: set[str] = set()
    for fn_name in ("pro_bar", "pro_bar_vip"):
        fn = getattr(ts, fn_name, None)
        if fn is None:
            continue
        apis.update(re.findall(r"api\.([a-z][a-z0-9_]*)\(", inspect.getsource(fn)))
    return sorted(apis)


def _probe_meta_apis(token: str) -> None:
    print("\n=== meta API 探测（SDK 无静态接口表，尝试常见 meta 名）===")
    candidates = [
        "api_list",
        "interface_list",
        "query_api",
        "apis",
        "interface",
        "user_info",
        "user",
        "token_info",
        "permission",
    ]
    for name in candidates:
        try:
            result = call_pro_api_raw(token, name, {}, max_calls_per_minute=500)
            msg = (result.msg or "")[:100]
            print(f"  {name:18s} code={result.code!s:6s} ok={str(result.ok):5s} msg={msg}")
        except Exception as exc:
            print(f"  {name:18s} EXC {exc}")


def _probe_sample(token: str) -> None:
    print("\n=== 常见接口 live 调用 ===")
    tests = {
        "trade_cal": {
            "exchange": "SSE",
            "start_date": "20240101",
            "end_date": "20240105",
            "fields": "exchange,cal_date",
        },
        "stock_basic": {"list_status": "L", "limit": 3, "fields": "ts_code,name"},
        "daily": {
            "ts_code": "000001.SZ",
            "start_date": "20240102",
            "end_date": "20240102",
        },
        "income": {"ts_code": "000001.SZ", "period": "20231231", "fields": "ts_code,end_date"},
        "top_inst": {"trade_date": "20240102", "fields": "ts_code,exalter"},
    }
    for api, params in tests.items():
        result = call_pro_api_raw(token, api, params, max_calls_per_minute=500)
        perm = parse_permission_info(result)
        rows = 0 if result.df is None else len(result.df)
        print(
            f"  {api:14s} code={result.code} rows={rows} "
            f"perm={perm['is_permission_error']} "
            f"live_pts={perm.get('api_live_min_points')} "
            f"level={perm.get('interface_level')}"
        )
        if not result.ok:
            print(f"    msg: {(result.msg or '')[:150]}")
            if result.data:
                print(f"    data: {str(result.data)[:200]}")


def _probe_official_index(token: str, *, limit: int = 58) -> dict[str, int]:
    print(f"\n=== 官方索引 stock_a live 探测（最多 {limit} 个，有 probe 规格）===")
    snap = build_document2_official_index(index_scope="stock_a")
    official_map = snap.as_map()
    stats: Counter[str] = Counter()
    live_points: list[dict] = []

    probed = 0
    for entry in sorted(snap.apis, key=lambda e: (e.doc_id or 99999, e.api)):
        if probed >= limit:
            break
        spec, _, _ = resolve_probe_spec(entry.api, entry)
        if not spec:
            stats["skipped_no_spec"] += 1
            continue
        raw_params = dict(spec.get("params") or {})
        from app.catalog.tia_probe_registry import resolve_probe_params
        from app.sync.tia_collect.params import sanitize_collect_params

        params = sanitize_collect_params(resolve_probe_params(raw_params))
        result = call_pro_api_raw(token, entry.api, params, max_calls_per_minute=500)
        perm = parse_permission_info(result)
        probed += 1

        if result.ok and result.df is not None and not result.df.empty:
            stats["ok"] += 1
            status = "ok"
        elif perm["is_permission_error"]:
            stats["failed_points"] += 1
            status = "failed_points"
            if perm.get("api_live_min_points") is not None:
                live_points.append(
                    {
                        "api": entry.api,
                        "min_points": perm["api_live_min_points"],
                        "level": perm.get("interface_level"),
                    }
                )
        elif result.ok:
            stats["failed_empty"] += 1
            status = "failed_empty"
        else:
            stats["failed"] += 1
            status = "failed"

        print(f"  {entry.api:20s} {status:16s} code={result.code} msg={(result.msg or '')[:60]}")

    print("\n统计:", dict(stats))
    if live_points:
        print("API 返回积分门槛样例:")
        for row in live_points[:10]:
            print(f"  {row}")
    return dict(stats)


def _inspect_error_codes(token: str) -> None:
    print("\n=== 错误码与权限响应样例 ===")
    snap = build_document2_official_index(index_scope="stock_a")
    targets = [
        "stk_auction_o",
        "fund_portfolio",
        "dc_index",
        "pro",
        "broker_rec",
        "barrelated",
        "margin_target",
        "ths_hot",
    ]
    from app.catalog.tia_probe_registry import resolve_probe_params
    from app.sync.tia_collect.params import sanitize_collect_params

    for api in targets:
        entry = snap.as_map().get(api)
        spec, _, _ = resolve_probe_spec(api, entry)
        if not spec:
            print(f"  {api:18s} (no probe spec)")
            continue
        params = sanitize_collect_params(resolve_probe_params(dict(spec.get("params") or {})))
        result = call_pro_api_raw(token, api, params, max_calls_per_minute=500)
        perm = parse_permission_info(result)
        print(f"  {api:18s} code={result.code} perm={perm['is_permission_error']} pts={perm.get('api_live_min_points')}")
        if result.msg:
            print(f"    msg: {result.msg[:200]}")
        if result.data:
            print(f"    data: {result.data}")


def main() -> None:
    token = get_settings().tushare_token or ts.get_token()
    if not token:
        print("ERROR: 未配置 TUSHARE token")
        sys.exit(1)

    print("=== tushare 包信息 ===")
    print(f"version: {ts.__version__}")
    print(f"path:    {ts.__file__}")
    print(f"顶层导出: {len([x for x in dir(ts) if not x.startswith('_')])} 个")
    print(f"Pro DataApi 显式方法: query + __getattr__（任意 api 名均可绑定）")
    print(f"pro_bar 硬编码引用: {len(_hardcoded_pro_bar_apis())} 个")
    print("  ", ", ".join(_hardcoded_pro_bar_apis()[:15]), "...")

    snap = build_document2_official_index(index_scope="stock_a")
    print(f"\nninehub document/2 stock_a 索引: {len(snap.apis)} 个 API")

    _probe_meta_apis(token)
    _probe_sample(token)
    stats = _probe_official_index(token)
    _inspect_error_codes(token)

    out = {
        "tushare_version": ts.__version__,
        "sdk_model": "dynamic __getattr__ — no static API registry in package",
        "pro_bar_hardcoded_apis": _hardcoded_pro_bar_apis(),
        "official_index_stock_a": len(snap.apis),
        "live_probe_stats": stats,
    }
    out_path = BACKEND / "scripts" / "_tushare_api_support_report.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入: {out_path}")


if __name__ == "__main__":
    main()
