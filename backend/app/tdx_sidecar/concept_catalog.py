"""Concept index/member snapshot from local TDX hq_cache files."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

BLOCK_MEMBER_CANDIDATES = ("block_gn.dat", "block_fg.dat", "block_zs.dat", "block.dat")


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


def _resolve_block_member_file(hq_cache_root: Path) -> tuple[Path | None, list[str]]:
    missing: list[str] = []
    for name in BLOCK_MEMBER_CANDIDATES:
        path = hq_cache_root / name
        if path.is_file():
            return path, missing
        missing.append(name)
    return None, missing


def _parse_block_members(
    path: Path,
    trade_date: date,
    *,
    index_name_map: dict[str, str],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        from pytdx.reader import BlockReader

        reader = BlockReader()
        blocks = reader.get_df(str(path))
        if blocks is None or blocks.empty:
            return rows
        for _, row in blocks.iterrows():
            blockname = str(row.get("blockname") or "").strip()
            stock_raw = str(row.get("code") or "").strip()
            index_code = index_name_map.get(blockname) or blockname
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
    except Exception:
        return rows
    return rows


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
    if hq_cache_root:
        cache_root = Path(hq_cache_root)
        tdxzs = cache_root / "tdxzs.cfg"
        index_rows = _parse_tdxzs(tdxzs)
        index_name_map = _index_name_map(tdxzs)
        block_path, missing_names = _resolve_block_member_file(cache_root)
        if block_path is not None:
            member_rows = _parse_block_members(
                block_path,
                trade_date,
                index_name_map=index_name_map,
            )
            member_source = block_path.name
            if index_rows and member_rows:
                source = f"local:tdxzs+{block_path.name}"
            elif index_rows:
                source = "local:tdxzs"
        else:
            member_missing_reason = (
                "未找到板块成分股文件（"
                + " / ".join(missing_names)
                + "）。请在通达信客户端执行「系统 → 专业数据 → 板块数据」更新后重试。"
            )
            if index_rows:
                source = "local:tdxzs"
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
    }


def concept_index_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    rows = payload.get("concept_index") or []
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def concept_member_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    rows = payload.get("concept_member") or []
    return pd.DataFrame(rows) if rows else pd.DataFrame()
