"""Export platform catalog schema as JSON Schema (consumer contract)."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any

_JSON_TYPE_MAP = {
    "string": "string",
    "date": "string",
    "number": "number",
    "integer": "integer",
    "boolean": "boolean",
}

SUPPORTED_EXPORT_FORMATS = frozenset({"json_schema", "openapi"})
SUPPORTED_BUNDLE_FORMATS = frozenset({"zip_json_schema", "zip_openapi", "openapi"})


def _property_schema(col: dict[str, Any]) -> dict[str, Any]:
    col_type = col.get("type") or "string"
    prop: dict[str, Any] = {
        "type": _JSON_TYPE_MAP.get(col_type, "string"),
        "title": col.get("label") or col.get("key"),
    }
    if col_type == "date":
        prop["format"] = "date"
    api_field = col.get("api_field")
    if api_field and api_field != col.get("key"):
        prop["description"] = f"源字段: {api_field}"
    return prop


def build_json_schema(
    *,
    api_name: str,
    data_type: str,
    label: str,
    table_name: str,
    provider_id: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """Build JSON Schema draft-07 document from L3 platform schema."""
    columns = schema.get("columns") or []
    unique_keys = list(schema.get("unique_keys") or [])
    properties: dict[str, Any] = {}
    required: list[str] = []

    for col in columns:
        key = col.get("key")
        if not key:
            continue
        properties[key] = _property_schema(col)
        if key in unique_keys or not col.get("nullable", True):
            required.append(key)

    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": f"ninehub://catalog/{data_type}",
        "title": label,
        "description": (
            f"NineHub 平台事实表契约 — provider={provider_id}, api={api_name}, table={table_name}"
        ),
        "type": "object",
        "properties": properties,
        "required": sorted(set(required)),
        "additionalProperties": False,
        "x-ninehub": {
            "api_name": api_name,
            "data_type": data_type,
            "table_name": table_name,
            "provider_id": provider_id,
            "unique_keys": unique_keys,
            "field_mappings": schema.get("field_mappings") or {},
            "indexes": schema.get("indexes") or [],
        },
    }


def json_schema_to_openapi_component(json_schema: dict[str, Any]) -> dict[str, Any]:
    """Strip JSON Schema meta keys for OpenAPI components.schemas."""
    component = dict(json_schema)
    for key in ("$schema", "$id"):
        component.pop(key, None)
    return component


def build_openapi_document(
    entries: list[dict[str, Any]],
    *,
    title: str = "NineHub Catalog Schemas",
) -> dict[str, Any]:
    """Build OpenAPI 3.0 fragment with all fact-table row schemas."""
    components: dict[str, Any] = {}
    for entry in entries:
        data_type = entry["data_type"]
        components[data_type] = json_schema_to_openapi_component(entry["json_schema"])

    row_one_of = [{"$ref": f"#/components/schemas/{dt}"} for dt in components]
    if not row_one_of:
        row_one_of = [{"type": "object"}]

    return {
        "openapi": "3.0.3",
        "info": {
            "title": title,
            "version": "1.0.0",
            "description": "NineHub 平台事实表行契约（由 data-standards export 生成）",
        },
        "paths": {
            "/api/v1/catalog/data/{data_type}": {
                "get": {
                    "summary": "浏览已激活事实表",
                    "parameters": [
                        {
                            "name": "data_type",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {"name": "skip", "in": "query", "schema": {"type": "integer", "default": 0}},
                        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 50}},
                    ],
                    "responses": {
                        "200": {
                            "description": "分页事实表行",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "items": {
                                                "type": "array",
                                                "items": {"oneOf": row_one_of},
                                            },
                                            "total": {"type": "integer"},
                                            "data_type": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
        "components": {"schemas": components},
    }


def build_export_zip(
    entries: list[dict[str, Any]],
    *,
    bundle_format: str,
) -> bytes:
    """Pack schema exports into zip (json files + optional openapi.json)."""
    buffer = io.BytesIO()
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(entries),
        "format": bundle_format,
        "items": [
            {
                "api_name": e["api_name"],
                "data_type": e["data_type"],
                "label": e["label"],
                "file": e.get("file"),
            }
            for e in entries
        ],
    }
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for entry in entries:
            zf.writestr(
                entry["file"],
                json.dumps(entry["json_schema"], indent=2, ensure_ascii=False),
            )
        if bundle_format == "zip_openapi":
            openapi_doc = build_openapi_document(entries)
            zf.writestr("openapi.json", json.dumps(openapi_doc, indent=2, ensure_ascii=False))
    return buffer.getvalue()
