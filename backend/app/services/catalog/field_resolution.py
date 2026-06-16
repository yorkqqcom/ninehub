"""Merge probe expected_fields, bundled registry, and live probe columns."""

from __future__ import annotations

from typing import Any

from app.catalog.api_output_fields_registry import registry_output_fields
from app.catalog.tia_probe_registry import api_probe_meta


def merge_field_lists(*sources: list[str] | None) -> list[str]:
    """Stable-order union of field name lists."""
    seen: set[str] = set()
    merged: list[str] = []
    for source in sources:
        if not source:
            continue
        for field in source:
            if field in seen:
                continue
            seen.add(field)
            merged.append(field)
    return merged


def resolve_expected_fields(api_name: str) -> list[str]:
    """Probe/template expected_fields only (no registry or live merge)."""
    from app.services.tia.scan.probe_planner import resolve_probe_spec

    spec, _, _ = resolve_probe_spec(api_name, None)
    if spec:
        explicit = list(spec.get("expected_fields") or [])
        if explicit:
            return explicit

    meta = api_probe_meta(api_name) or {}
    probe = meta.get("probe") or {}
    explicit = list(probe.get("expected_fields") or [])
    if explicit:
        return explicit

    from app.catalog.tia_probe_registry import OFFICIAL_ONLY_API_PROBES

    oo_probe = (OFFICIAL_ONLY_API_PROBES.get(api_name) or {}).get("probe") or {}
    oo_fields = list(oo_probe.get("expected_fields") or [])
    if oo_fields:
        return oo_fields

    from app.services.tia.scan.probe_templates import PROBE_TEMPLATES
    from app.services.tia.scan.tushare_doc_registry import infer_probe_category, load_api_by_doc_id

    probe_category = None
    for row in load_api_by_doc_id().values():
        if row.get("api") == api_name:
            probe_category = infer_probe_category(
                category=row.get("category"),
                subcategory=row.get("subcategory"),
                explicit=row.get("probe_category"),
            )
            break
    if probe_category and probe_category != "none":
        tpl = PROBE_TEMPLATES.get(probe_category) or {}
        template_fields = list(tpl.get("expected_fields") or [])
        if template_fields:
            return template_fields
    return []


def resolve_api_fields(
    api_name: str,
    actual_fields: list[str] | None = None,
    *,
    live_fields: list[str] | None = None,
    require_live_actual: bool = False,
) -> list[str]:
    """Resolve API field list for schema / DDL.

    L3 建表以实盘探针 ``actual_fields`` 为唯一来源（文档/registry 仅作预览兜底）。

    Priority:
    1. explicit actual_fields (caller override, tests / manual)
    2. live_fields — 实盘探针返回列（审批激活建表依据）
    3. merge(expected_fields, registry_output_fields) — 仅 catalog 预览 / live_probe=false
    """
    if actual_fields:
        return list(actual_fields)
    if live_fields:
        return list(live_fields)
    if require_live_actual:
        from app.core.exceptions import ValidationError

        raise ValidationError(
            f"DDL schema for '{api_name}' requires live probe actual_fields; "
            "configure Tushare token and run preflight first"
        )
    expected = resolve_expected_fields(api_name)
    registry = registry_output_fields(api_name)
    return merge_field_lists(expected, registry)


def live_fields_from_activation_steps(steps: dict[str, Any] | None) -> list[str] | None:
    """Extract live probe column list saved on proposal activation_steps."""
    if not steps:
        return None
    preflight = steps.get("preflight_test") or {}
    actual = preflight.get("actual_fields")
    if actual:
        return list(actual)
    return None
