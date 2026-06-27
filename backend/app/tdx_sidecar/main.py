"""FastAPI sidecar for TDX T+1 batch import."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.tdx_sidecar.concept_catalog import (
    concept_index_dataframe,
    concept_member_dataframe,
    export_concept_catalog,
)
from app.tdx_sidecar.network_bars import fetch_network_bars_batch
from app.tdx_sidecar.paths import (
    merge_paths_config,
    resolve_effective_paths,
    save_runtime_config,
)
from app.tdx_sidecar.vipdoc_reader import import_vipdoc_bars, scan_vipdoc_status

app = FastAPI(title="NineHub TDX Sidecar", version="0.1.0")

_API_TOKEN = os.environ.get("TDX_SIDECAR_API_TOKEN") or os.environ.get("API_TOKEN") or ""


def _require_token(authorization: str | None = Header(default=None)) -> None:
    if not _API_TOKEN:
        return
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization")
    token = authorization.removeprefix("Bearer ").strip()
    if token != _API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


class PathsOverride(BaseModel):
    vipdoc_root: str | None = None
    hq_cache_root: str | None = None
    concept_export_dir: str | None = None
    connect_cfg_path: str | None = None


class TdxConfigPatch(BaseModel):
    install_root: str | None = None
    connect_cfg_path: str | None = None
    vipdoc_root: str | None = None
    hq_cache_root: str | None = None
    concept_export_dir: str | None = None


class VipdocImportRequest(BaseModel):
    period: str = "1d"
    start_date: date | None = None
    end_date: date | None = None
    stock_codes: list[str] | None = None
    incremental: bool = False
    last_sync_date: date | None = None
    limit_files: int | None = Field(default=None, ge=1, le=10000)
    install_root: str | None = None
    paths: PathsOverride | None = None


class BarsBatchRequest(BaseModel):
    period: str = "1d"
    start_date: date
    end_date: date
    stock_codes: list[str] = Field(min_length=1)
    install_root: str | None = None
    paths: PathsOverride | None = None


def _records_from_df(df) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    out = df.copy()
    for col in out.columns:
        sample = out[col].dropna()
        if sample.empty:
            continue
        if hasattr(sample.iloc[0], "isoformat"):
            out[col] = out[col].apply(lambda x: x.isoformat() if x is not None else None)
    return out.to_dict(orient="records")


def _resolve_paths(body_install: str | None, paths: PathsOverride | None):
    override = paths.model_dump(exclude_none=True) if paths else None
    cfg = merge_paths_config(install_root=body_install, paths=override)
    return resolve_effective_paths(cfg)


@app.get("/api/v1/market/health")
def health(_: None = Depends(_require_token)) -> dict[str, Any]:
    return {"status": "ok", "backend": "tdx_sidecar"}


@app.get("/api/v1/market/tdx-config")
def get_tdx_config(_: None = Depends(_require_token)) -> dict[str, Any]:
    cfg = merge_paths_config()
    eff = resolve_effective_paths(cfg)
    return {
        "install_root": eff.install_root,
        "runtime_config": cfg.__dict__,
        "effective_paths": {
            "vipdoc_root": eff.vipdoc_root,
            "vipdoc_sh_lday": eff.vipdoc_sh_lday,
            "vipdoc_sz_lday": eff.vipdoc_sz_lday,
            "hq_cache_root": eff.hq_cache_root,
            "concept_export_dir": eff.concept_export_dir,
            "connect_cfg_path": eff.connect_cfg_path,
        },
        "probes": eff.probes,
    }


@app.put("/api/v1/market/tdx-config")
def put_tdx_config(body: TdxConfigPatch, _: None = Depends(_require_token)) -> dict[str, Any]:
    saved = save_runtime_config(body.model_dump(exclude_unset=True))
    cfg = merge_paths_config()
    eff = resolve_effective_paths(cfg)
    return {"saved": saved, "effective_paths": eff.__dict__, "probes": eff.probes}


@app.get("/api/v1/market/vipdoc/status")
def vipdoc_status(
    install_root: str | None = None,
    vipdoc_root: str | None = None,
    _: None = Depends(_require_token),
) -> dict[str, Any]:
    override = {"vipdoc_root": vipdoc_root} if vipdoc_root else None
    cfg = merge_paths_config(install_root=install_root, paths=override)
    eff = resolve_effective_paths(cfg)
    scan = scan_vipdoc_status(eff.vipdoc_root) if eff.vipdoc_root else {}
    return {
        "install_root": eff.install_root,
        "effective_paths": {
            "vipdoc_root": eff.vipdoc_root,
            "vipdoc_sh_lday": eff.vipdoc_sh_lday,
            "vipdoc_sz_lday": eff.vipdoc_sz_lday,
            "hq_cache_root": eff.hq_cache_root,
        },
        "probes": eff.probes,
        **scan,
    }


@app.post("/api/v1/market/vipdoc/import")
def vipdoc_import(body: VipdocImportRequest, _: None = Depends(_require_token)) -> dict[str, Any]:
    eff = _resolve_paths(body.install_root, body.paths)
    if not eff.vipdoc_root:
        raise HTTPException(status_code=400, detail="vipdoc_root not configured")
    df, meta = import_vipdoc_bars(
        eff.vipdoc_root,
        period=body.period,
        start_date=body.start_date,
        end_date=body.end_date,
        stock_codes=body.stock_codes,
        incremental=body.incremental,
        last_sync_date=body.last_sync_date,
        limit_files=body.limit_files,
    )
    return {"items": _records_from_df(df), "meta": meta}


@app.post("/api/v1/market/bars/batch")
def bars_batch(body: BarsBatchRequest, _: None = Depends(_require_token)) -> dict[str, Any]:
    eff = _resolve_paths(body.install_root, body.paths)
    df, meta = fetch_network_bars_batch(
        stock_codes=body.stock_codes,
        period=body.period,
        start_date=body.start_date,
        end_date=body.end_date,
        connect_cfg_path=eff.connect_cfg_path,
    )
    return {"items": _records_from_df(df), "meta": meta}


@app.get("/api/v1/market/concept-catalog")
def concept_catalog(
    trade_date: date,
    install_root: str | None = None,
    hq_cache_root: str | None = None,
    _: None = Depends(_require_token),
) -> dict[str, Any]:
    override = {"hq_cache_root": hq_cache_root} if hq_cache_root else None
    cfg = merge_paths_config(install_root=install_root, paths=override)
    eff = resolve_effective_paths(cfg)
    payload = export_concept_catalog(
        hq_cache_root=eff.hq_cache_root,
        concept_export_dir=eff.concept_export_dir,
        trade_date=trade_date,
    )
    payload["concept_index_items"] = _records_from_df(concept_index_dataframe(payload))
    payload["concept_member_items"] = _records_from_df(concept_member_dataframe(payload))
    return payload
