"""Parse Tushare interface specs from wctapi markdown (document/2 doc_id pages)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.services.tia.scan.min_points_extractor import extract_access_min_points
from app.services.tia.scan.tushare_doc_registry import build_doc_page_url, parse_api_name_from_doc_text

_WCTAPI_MD_BASE = "https://tushare.pro/wctapi/documents"
_CODE_BLOCK_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.I | re.S)
_TABLE_ROW_RE = re.compile(r"^\s*\|(.+)\|\s*$", re.M)


@dataclass
class DocParamField:
    name: str
    type: str | None = None
    required: str | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ApiDocSpec:
    doc_id: int
    api: str
    doc_url: str
    doc_md_url: str
    description: str | None = None
    input_params: list[DocParamField] = field(default_factory=list)
    output_params: list[DocParamField] = field(default_factory=list)
    output_fields: list[str] = field(default_factory=list)
    sample_codes: list[str] = field(default_factory=list)
    min_points: int | None = None
    sdk_valid: bool | None = None
    sdk_validation_code: int | None = None
    sdk_validation_msg: str | None = None
    spec_source: str = "wctapi_md"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["input_params"] = [p if isinstance(p, dict) else p.to_dict() for p in self.input_params]
        data["output_params"] = [p if isinstance(p, dict) else p.to_dict() for p in self.output_params]
        return data

    def probe_spec(self) -> dict[str, Any]:
        """Build probe params + expected_fields for live API scan."""
        from app.services.tia.scan.probe_spec_from_doc import build_probe_spec_from_doc

        return build_probe_spec_from_doc(self)


def build_wctapi_md_url(doc_id: int) -> str:
    return f"{_WCTAPI_MD_BASE}/{int(doc_id)}.md"


def _split_section(text: str, header: str) -> str:
    pattern = re.compile(rf"\*\*{re.escape(header)}\*\*", re.I)
    match = pattern.search(text)
    if not match:
        return ""
    rest = text[match.end() :]
    next_header = re.search(r"\*\*[^*]+\*\*", rest)
    return rest[: next_header.start()] if next_header else rest


def _parse_markdown_table(section: str, *, with_required: bool) -> list[DocParamField]:
    rows: list[list[str]] = []
    for line in section.splitlines():
        stripped = line.strip()
        if "|" not in stripped:
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells or cells[0] in ("名称", "name", "---", "----"):
            continue
        if all(set(c) <= {"-", ":"} for c in cells if c):
            continue
        rows.append(cells)

    fields: list[DocParamField] = []
    for cells in rows:
        if with_required and len(cells) >= 4:
            fields.append(
                DocParamField(
                    name=cells[0],
                    type=cells[1] or None,
                    required=cells[2] or None,
                    description=cells[3] or None,
                )
            )
        elif len(cells) >= 4 and not with_required:
            # output table with 默认显示 column
            fields.append(
                DocParamField(
                    name=cells[0],
                    type=cells[1] or None,
                    description=cells[3] if len(cells) > 3 else (cells[2] or None),
                )
            )
        elif len(cells) >= 3:
            fields.append(
                DocParamField(
                    name=cells[0],
                    type=cells[1] or None,
                    description=cells[2] or None,
                )
            )
        elif len(cells) >= 1 and cells[0]:
            fields.append(DocParamField(name=cells[0]))
    return fields


def _extract_description(text: str) -> str | None:
    match = re.search(r"描述[：:]\s*(.+?)(?:\n|$)", text)
    if match:
        return match.group(1).strip()
    return None


def parse_wctapi_markdown(doc_id: int, markdown: str) -> ApiDocSpec | None:
    """Parse one wctapi markdown page into structured ApiDocSpec."""
    if not markdown or not markdown.strip():
        return None

    api = parse_api_name_from_doc_text(markdown)
    if not api:
        header_match = re.search(r"接口[：:]\s*([a-z][a-z0-9_]*)", markdown, re.I)
        if header_match:
            api = header_match.group(1).lower()

    if not api:
        return None

    input_section = _split_section(markdown, "输入参数")
    output_section = _split_section(markdown, "输出参数")
    input_params = _parse_markdown_table(input_section, with_required=True)
    output_params = _parse_markdown_table(output_section, with_required=False)
    output_fields = [p.name for p in output_params if p.name]

    sample_codes = [block.strip() for block in _CODE_BLOCK_RE.findall(markdown) if block.strip()]
    min_points = extract_access_min_points(markdown)
    doc_url = build_doc_page_url(doc_id) or f"https://tushare.pro/document/2?doc_id={doc_id}"

    return ApiDocSpec(
        doc_id=int(doc_id),
        api=api,
        doc_url=doc_url,
        doc_md_url=build_wctapi_md_url(doc_id),
        description=_extract_description(markdown),
        input_params=input_params,
        output_params=output_params,
        output_fields=output_fields,
        sample_codes=sample_codes,
        min_points=min_points,
    )
