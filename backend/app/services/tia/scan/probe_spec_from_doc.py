"""Build live-probe call specs from parsed document input/output params."""

from __future__ import annotations

from typing import Any

from app.services.tia.scan.doc_spec_parser import ApiDocSpec, DocParamField

_DEFAULT_PARAM_VALUES: dict[str, Any] = {
    "ts_code": "000001.SZ",
    "symbol": "000001.SZ",
    "trade_date": "__LAST_TRADING_DAY__",
    "start_date": "20240102",
    "end_date": "20240105",
    "ann_date": "20240131",
    "period": "20231231",
    "end_date_fin": "20231231",
    "exchange": "SSE",
    "list_status": "L",
    "limit": 3,
    "offset": 0,
    "freq": "D",
    "month": "202401",
}


def _param_names(spec: ApiDocSpec) -> set[str]:
    return {p.name for p in spec.input_params if p.name}


def build_probe_params_from_doc(spec: ApiDocSpec) -> dict[str, Any]:
    """Map documented input params to minimal probe call params."""
    names = _param_names(spec)
    params: dict[str, Any] = {}

    for name in names:
        if name in _DEFAULT_PARAM_VALUES:
            params[name] = _DEFAULT_PARAM_VALUES[name]
        elif name.endswith("_date") and "start" not in name and "end" not in name:
            params[name] = "__LAST_TRADING_DAY__"

    # date-range APIs: ensure start/end pair when documented
    if "ts_code" in names and {"start_date", "end_date"} <= names:
        params.setdefault("ts_code", "000001.SZ")
        params.setdefault("start_date", "20240102")
        params.setdefault("end_date", "20240105")
    elif "trade_date" in names and len(names) <= 2:
        params.setdefault("trade_date", "__LAST_TRADING_DAY__")
    elif "exchange" in names and {"start_date", "end_date"} <= names:
        params.setdefault("exchange", "SSE")
        params.setdefault("start_date", "20240101")
        params.setdefault("end_date", "20240105")
    elif "period" in names and "ts_code" in names:
        params.setdefault("ts_code", "000001.SZ")
        params.setdefault("period", "20231231")
    elif "list_status" in names or ("exchange" in names and "ts_code" not in names):
        params.setdefault("exchange", "")
        params.setdefault("list_status", "L")
        params.setdefault("limit", 3)
    elif not params and names:
        # fallback: first documented param with generic value
        first = next(iter(names))
        params[first] = _DEFAULT_PARAM_VALUES.get(first, "")

    return params


def build_probe_spec_from_doc(spec: ApiDocSpec) -> dict[str, Any]:
    params = build_probe_params_from_doc(spec)
    expected = list(spec.output_fields)
    if expected and "fields" not in params:
        # keep full column set for field diff; do not pass fields= to pro API
        pass
    return {
        "params": params,
        "expected_fields": expected,
        "doc_id": spec.doc_id,
        "doc_url": spec.doc_url,
        "sample_codes": spec.sample_codes[:3],
        "input_params": [p.to_dict() for p in spec.input_params],
        "output_params": [p.to_dict() for p in spec.output_params],
    }


def api_doc_spec_from_cache_row(row: dict[str, Any]) -> ApiDocSpec | None:
    if not row.get("api"):
        return None

    def _fields(key: str) -> list[DocParamField]:
        out: list[DocParamField] = []
        for item in row.get(key) or []:
            if isinstance(item, dict) and item.get("name"):
                out.append(
                    DocParamField(
                        name=str(item["name"]),
                        type=item.get("type"),
                        required=item.get("required"),
                        description=item.get("description"),
                    )
                )
        return out

    return ApiDocSpec(
        doc_id=int(row["doc_id"]),
        api=str(row["api"]),
        doc_url=str(row.get("doc_url") or ""),
        doc_md_url=str(row.get("doc_md_url") or ""),
        description=row.get("description"),
        input_params=_fields("input_params"),
        output_params=_fields("output_params"),
        output_fields=list(row.get("output_fields") or []),
        sample_codes=list(row.get("sample_codes") or []),
        min_points=row.get("min_points"),
        sdk_valid=row.get("sdk_valid"),
        sdk_validation_code=row.get("sdk_validation_code"),
        sdk_validation_msg=row.get("sdk_validation_msg"),
        spec_source=str(row.get("spec_source") or "wctapi_md"),
    )
