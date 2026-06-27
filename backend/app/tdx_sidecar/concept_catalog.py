"""Concept index/member snapshot from local TDX hq_cache files."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


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


def _parse_block_gn(path: Path, trade_date: date) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    try:
        from pytdx.reader import BlockReader

        reader = BlockReader()
        blocks = reader.get_df(str(path))
        if blocks is None or blocks.empty:
            return rows
        for _, row in blocks.iterrows():
            index_raw = str(row.get("blockname") or row.get("code") or "")
            stock_raw = str(row.get("code") or "")
            if not index_raw or not stock_raw:
                continue
            rows.append(
                {
                    "index_code": index_raw,
                    "stock_code": stock_raw,
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
    if hq_cache_root:
        tdxzs = Path(hq_cache_root) / "tdxzs.cfg"
        index_rows = _parse_tdxzs(tdxzs)
        block_gn = Path(hq_cache_root) / "block_gn.dat"
        if block_gn.is_file():
            member_rows = _parse_block_gn(block_gn, trade_date)
            source = "local:tdxzs+block_gn"
    if index_rows:
        for row in index_rows:
            row["trade_date"] = trade_date.isoformat()
    return {
        "trade_date": trade_date.isoformat(),
        "concept_map_source": source,
        "concept_index": index_rows,
        "concept_member": member_rows,
    }


def concept_index_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    rows = payload.get("concept_index") or []
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def concept_member_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
    rows = payload.get("concept_member") or []
    return pd.DataFrame(rows) if rows else pd.DataFrame()
