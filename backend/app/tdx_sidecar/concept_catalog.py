"""Concept index/member snapshot from local TDX hq_cache files."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# 概念成分主源：仅 block_gn；与 export 多类板块 txt 做并集（勿用其它 block 挡 export）
BLOCK_GN_NAME = "block_gn.dat"
EXPORT_MEMBER_CANDIDATES = (
    "概念板块.txt",
    "地区板块.txt",
    "行业板块.txt",
    "风格板块.txt",
    "指数板块.txt",
)


def _normalize_stock_code(raw: str) -> str | None:
    code = raw.strip()
    if len(code) != 6 or not code.isdigit():
        return None
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _index_name_map(tdxzs_path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for row in _parse_tdxzs(tdxzs_path):
        name = str(row.get("name") or "").strip()
        index_code = str(row.get("index_code") or "").strip()
        if name and index_code:
            mapping[name] = index_code
    return mapping


def _parse_tdxzs(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="gbk", errors="ignore").splitlines():
        parts = line.strip().split("|")
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        code = parts[1].strip()
        if code.isdigit() and len(code) == 6:
            rows.append({"index_code": f"{code}.TDX", "name": name})
    return rows


def _iter_export_member_files(export_dir: Path) -> list[Path]:
    found: list[Path] = []
    for name in EXPORT_MEMBER_CANDIDATES:
        path = export_dir / name
        if path.is_file() and path.stat().st_size > 0:
            found.append(path)
    return found


def _normalize_index_code(raw: str) -> str | None:
    code = raw.strip()
    if len(code) == 6 and code.isdigit():
        return f"{code}.TDX"
    if code.endswith(".TDX"):
        return code
    return None


def _dedupe_members(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """按 (index, stock) 去重；后到行可补全先到行缺失的 stock_name。"""
    by_key: dict[tuple[str, str], dict[str, str]] = {}
    order: list[tuple[str, str]] = []
    for row in rows:
        key = (row.get("index_code") or "", row.get("stock_code") or "")
        if not key[0] or not key[1]:
            continue
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = dict(row)
            order.append(key)
            continue
        if not str(prev.get("stock_name") or "").strip() and str(row.get("stock_name") or "").strip():
            prev["stock_name"] = str(row["stock_name"]).strip()
    return [by_key[k] for k in order]


def _parse_export_members(path: Path, trade_date: date) -> list[dict[str, str]]:
    """Parse TongDaXin export txt: index_code\\tname\\tstock_code\\tstock_name."""
    rows: list[dict[str, str]] = []
    for line in path.read_text(encoding="gbk", errors="ignore").splitlines():
        parts = line.strip().split("\t")
        if len(parts) < 3:
            continue
        index_code = _normalize_index_code(parts[0])
        stock_code = _normalize_stock_code(parts[2])
        if not index_code or not stock_code:
            continue
        stock_name = parts[3].strip() if len(parts) > 3 else ""
        row: dict[str, str] = {
            "index_code": index_code,
            "stock_code": stock_code,
            "trade_date": trade_date.isoformat(),
        }
        if stock_name:
            row["stock_name"] = stock_name
        rows.append(row)
    return rows


def _parse_block_members(
    path: Path,
    trade_date: date,
    *,
    index_name_map: dict[str, str],
) -> tuple[list[dict[str, str]], int]:
    """Parse block_gn.dat; skip rows whose blockname is not in tdxzs map.

    Returns (rows, unmapped_block_count).
    """
    rows: list[dict[str, str]] = []
    unmapped = 0
    try:
        from pytdx.reader import BlockReader

        reader = BlockReader()
        blocks = reader.get_df(str(path))
        if blocks is None or blocks.empty:
            return rows, unmapped
        for _, row in blocks.iterrows():
            blockname = str(row.get("blockname") or "").strip()
            stock_raw = str(row.get("code") or "").strip()
            mapped = index_name_map.get(blockname)
            if not mapped:
                if blockname:
                    unmapped += 1
                continue
            index_code = _normalize_index_code(mapped)
            stock_code = _normalize_stock_code(stock_raw)
            if not index_code or not stock_code:
                continue
            rows.append(
                {
                    "index_code": index_code,
                    "stock_code": stock_code,
                    "trade_date": trade_date.isoformat(),
                }
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("parse block members failed path=%s: %s", path, exc)
        return rows, unmapped
    return rows, unmapped


def export_concept_catalog(
    *,
    hq_cache_root: str | None,
    concept_export_dir: str | None,
    trade_date: date,
) -> dict[str, Any]:
    index_rows: list[dict[str, str]] = []
    member_rows: list[dict[str, str]] = []
    source = "none"
    member_source: str | None = None
    member_missing_reason: str | None = None
    unmapped_block_count = 0
    source_parts: list[str] = []

    if hq_cache_root:
        cache_root = Path(hq_cache_root)
        tdxzs = cache_root / "tdxzs.cfg"
        index_rows = _parse_tdxzs(tdxzs)
        index_name_map = _index_name_map(tdxzs)

        gn_path = cache_root / BLOCK_GN_NAME
        if gn_path.is_file():
            gn_rows, unmapped_block_count = _parse_block_members(
                gn_path,
                trade_date,
                index_name_map=index_name_map,
            )
            if gn_rows:
                member_rows.extend(gn_rows)
                source_parts.append(BLOCK_GN_NAME)

        export_files: list[Path] = []
        if concept_export_dir:
            export_files = _iter_export_member_files(Path(concept_export_dir))
        for export_path in export_files:
            member_rows.extend(_parse_export_members(export_path, trade_date))
        if export_files:
            source_parts.append("export:merged" if len(export_files) > 1 else f"export:{export_files[0].name}")

        member_rows = _dedupe_members(member_rows)
        if source_parts:
            member_source = "+".join(source_parts)

        if index_rows and member_rows:
            source = f"local:tdxzs+{member_source}"
        elif index_rows:
            source = "local:tdxzs"

        if not member_rows:
            hints: list[str] = []
            if not gn_path.is_file():
                hints.append(f"缺失 {BLOCK_GN_NAME}")
            elif BLOCK_GN_NAME not in source_parts:
                hints.append(f"{BLOCK_GN_NAME} 无可用映射成分")
            if not export_files:
                hints.append("缺失 " + " / ".join(EXPORT_MEMBER_CANDIDATES))
            else:
                hints.append("export 已读但无有效成分行")
            member_missing_reason = (
                "未找到可用的板块成分（"
                + "；".join(hints)
                + "）。请在通达信客户端执行「系统 → 专业数据 → 板块数据」更新 block_gn.dat，"
                "或导出概念/地区/行业/风格/指数板块到 T0002/export 后重试。"
            )

    if index_rows:
        for row in index_rows:
            row["trade_date"] = trade_date.isoformat()
    return {
        "trade_date": trade_date.isoformat(),
        "concept_map_source": source,
        "concept_index": index_rows,
        "concept_member": member_rows,
        "concept_member_source": member_source,
        "concept_member_missing_reason": member_missing_reason,
        "unmapped_block_count": unmapped_block_count,
    }


def concept_index_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    rows = payload.get("concept_index") or []
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def concept_member_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    rows = payload.get("concept_member") or []
    return pd.DataFrame(rows) if rows else pd.DataFrame()
