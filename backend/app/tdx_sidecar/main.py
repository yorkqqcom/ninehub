"""FastAPI sidecar for TDX T+1 batch import + market ranks."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from app.tdx_sidecar.concept_catalog import (
    concept_index_dataframe,
    concept_member_dataframe,
    export_concept_catalog,
)
from app.tdx_sidecar.network_bars import all_codes_are_concept_index, fetch_network_bars_batch
from app.tdx_sidecar.paths import (
    merge_paths_config,
    resolve_effective_paths,
    save_runtime_config,
)
from app.tdx_sidecar.quotes import fetch_quotes_batch
from app.tdx_sidecar.ranks import get_rank_engine
from app.tdx_sidecar.vipdoc_reader import import_vipdoc_bars, scan_vipdoc_status

logger = logging.getLogger(__name__)

_API_TOKEN = os.environ.get("TDX_SIDECAR_API_TOKEN") or os.environ.get("API_TOKEN") or ""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import sys

    logger.info("tdx sidecar starting executable=%s cwd=%s", sys.executable, os.getcwd())
    engine = get_rank_engine()
    # 先载目录写入 stock name 缓存，避免 warm 未起 / 首轮未完时股池名称全空
    try:
        engine.bootstrap_catalog()
    except Exception as exc:  # noqa: BLE001
        logger.warning("rank catalog bootstrap failed: %s", exc)
    # Tests / constrained hosts can disable: TDX_SIDECAR_RANK_WARM=0
    warm = (os.environ.get("TDX_SIDECAR_RANK_WARM") or "1").strip().lower()
    if warm not in {"0", "false", "no", "off"}:
        engine.start()
    try:
        yield
    finally:
        engine.stop(join_timeout=2.0)


app = FastAPI(title="NineHub TDX Sidecar", version="0.2.0", lifespan=lifespan)


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


class QuotesRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=100)
    install_root: str | None = None
    paths: PathsOverride | None = None


class RanksSnapshotRequest(BaseModel):
    pool_symbols: list[str] = Field(default_factory=list)
    concept_code: str | None = None
    top_n: int = Field(default=30, ge=1, le=30)


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
    """Network bars with vipdoc fallback for 1d/1m when HQ empty or unreachable."""
    eff = _resolve_paths(body.install_root, body.paths)
    df, meta = fetch_network_bars_batch(
        stock_codes=body.stock_codes,
        period=body.period,
        start_date=body.start_date,
        end_date=body.end_date,
        connect_cfg_path=eff.connect_cfg_path,
    )
    network_error = str(meta.get("error") or "")
    need_fallback = df is None or df.empty
    period = (body.period or "").strip().lower()
    concept_only = all_codes_are_concept_index(body.stock_codes)

    if need_fallback and concept_only:
        degraded = True
        if "connect" in network_error.lower():
            message = "行情主机连接失败"
        elif period == "1m":
            message = "暂无概念分时"
        else:
            message = "暂无概念指数K线"
        return {
            "items": [],
            "degraded": degraded,
            "message": message,
            "meta": {
                **meta,
                "degraded": degraded,
                "error": network_error or meta.get("error"),
                "vipdoc_skipped": True,
                "reason": "concept_index",
            },
        }

    if need_fallback and period in {"1d", "1m"} and eff.vipdoc_root:
        try:
            vdf, vmeta = import_vipdoc_bars(
                eff.vipdoc_root,
                period=period,
                start_date=body.start_date,
                end_date=body.end_date,
                stock_codes=body.stock_codes,
            )
            if vdf is not None and not vdf.empty:
                meta = {
                    **vmeta,
                    "source": "vipdoc",
                    "network_error": network_error or None,
                    "degraded": bool(network_error),
                }
                message = ""
                if network_error:
                    message = "行情主机不可用，已使用本地 vipdoc"
                return {
                    "items": _records_from_df(vdf),
                    "degraded": bool(meta.get("degraded")),
                    "message": message,
                    "meta": meta,
                }
            meta = {
                **meta,
                "vipdoc_files_read": int(vmeta.get("files_read") or 0),
                "vipdoc_tried": True,
            }
        except FileNotFoundError as exc:
            meta = {**meta, "vipdoc_error": str(exc), "vipdoc_tried": True}
        except Exception as exc:  # noqa: BLE001
            logger.warning("vipdoc bars fallback failed: %s", exc)
            meta = {**meta, "vipdoc_error": str(exc), "vipdoc_tried": True}

    degraded = bool(meta.get("degraded")) or (need_fallback and bool(network_error))
    if need_fallback and not network_error:
        degraded = True
        network_error = network_error or "empty bars"
    message = ""
    if need_fallback:
        if "connect" in network_error.lower():
            message = "行情主机连接失败"
        elif period in {"1m", "5m"}:
            message = "暂无分钟线（非交易日或无本地分钟线）"
        else:
            message = "暂无 K 线数据"
        if meta.get("vipdoc_tried") and not message.endswith("vipdoc"):
            message = f"{message}；本地 vipdoc 亦无数据"

    return {
        "items": _records_from_df(df) if df is not None else [],
        "degraded": degraded,
        "message": message,
        "meta": {**meta, "degraded": degraded, "error": network_error or meta.get("error")},
    }



@app.post("/api/v1/market/quotes")
def market_quotes(body: QuotesRequest, _: None = Depends(_require_token)) -> dict[str, Any]:
    """Realtime batch quotes (pytdx). SH/SZ only; volume unit is TDX 手."""
    eff = _resolve_paths(body.install_root, body.paths)
    return fetch_quotes_batch(body.symbols, connect_cfg_path=eff.connect_cfg_path)


@app.post("/api/v1/market/ranks/snapshot")
def ranks_snapshot(body: RanksSnapshotRequest, _: None = Depends(_require_token)) -> dict[str, Any]:
    """Concept + pool rank snapshot (Cockpit lanes; no similar stocks)."""
    return get_rank_engine().snapshot(
        pool_symbols=body.pool_symbols,
        concept_code=body.concept_code,
        top_n=body.top_n,
    )


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
