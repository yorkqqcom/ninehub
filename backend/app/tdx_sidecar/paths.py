"""Resolve TongDaXin install_root and derived vipdoc / hq_cache paths."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DETECTED_ROOTS = (
    Path(r"C:\new_tdx"),
    Path(r"C:\tdx"),
    Path(r"C:\JCB_GJ"),
)


@dataclass
class TdxPathsConfig:
    install_root: str | None = None
    connect_cfg_path: str | None = None
    vipdoc_root: str | None = None
    hq_cache_root: str | None = None
    concept_export_dir: str | None = None


@dataclass
class EffectivePaths:
    install_root: str | None
    vipdoc_root: str
    hq_cache_root: str | None
    concept_export_dir: str | None
    connect_cfg_path: str | None
    vipdoc_sh_lday: str | None = None
    vipdoc_sz_lday: str | None = None
    vipdoc_sh_minline: str | None = None
    vipdoc_sz_minline: str | None = None
    probes: dict[str, Any] = field(default_factory=dict)


def _config_json_path(data_dir: Path | None = None) -> Path:
    root = data_dir or Path(os.environ.get("TDX_SIDECAR_DATA_DIR", "data"))
    root.mkdir(parents=True, exist_ok=True)
    return root / "tdx_config.json"


def load_runtime_config(data_dir: Path | None = None) -> dict[str, str | None]:
    path = _config_json_path(data_dir)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str | None] = {}
    for key in (
        "install_root",
        "connect_cfg_path",
        "vipdoc_root",
        "hq_cache_root",
        "concept_export_dir",
    ):
        val = raw.get(key)
        if val is not None and str(val).strip():
            out[key] = str(val).strip()
    return out


def save_runtime_config(patch: dict[str, Any], data_dir: Path | None = None) -> dict[str, str | None]:
    current = load_runtime_config(data_dir)
    for key in (
        "install_root",
        "connect_cfg_path",
        "vipdoc_root",
        "hq_cache_root",
        "concept_export_dir",
    ):
        if key not in patch:
            continue
        val = patch[key]
        if val is None or not str(val).strip():
            current.pop(key, None)
        else:
            current[key] = str(val).strip()
    path = _config_json_path(data_dir)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return current


def _is_tdx_root(path: Path) -> bool:
    return (path / "connect.cfg").is_file() or (path / "T0002").is_dir()


def autodetect_install_root() -> str | None:
    env_root = (os.environ.get("TDX_INSTALL_ROOT") or os.environ.get("XTQMT_TDX_INSTALL_ROOT") or "").strip()
    if env_root:
        p = Path(env_root)
        if p.is_dir() and _is_tdx_root(p):
            return str(p)
    for candidate in _DETECTED_ROOTS:
        if candidate.is_dir() and _is_tdx_root(candidate):
            return str(candidate)
    return None


def merge_paths_config(
    *,
    install_root: str | None = None,
    paths: dict[str, Any] | None = None,
    data_dir: Path | None = None,
) -> TdxPathsConfig:
    runtime = load_runtime_config(data_dir)
    merged = TdxPathsConfig(
        install_root=install_root or runtime.get("install_root") or autodetect_install_root(),
        connect_cfg_path=runtime.get("connect_cfg_path"),
        vipdoc_root=runtime.get("vipdoc_root"),
        hq_cache_root=runtime.get("hq_cache_root"),
        concept_export_dir=runtime.get("concept_export_dir"),
    )
    if paths:
        for key in ("vipdoc_root", "hq_cache_root", "concept_export_dir", "connect_cfg_path"):
            val = paths.get(key)
            if val is not None and str(val).strip():
                setattr(merged, key, str(val).strip())
    env_vipdoc = (os.environ.get("TDX_VIPDOC_ROOT") or "").strip()
    if env_vipdoc and not merged.vipdoc_root:
        merged.vipdoc_root = env_vipdoc
    return merged


def resolve_effective_paths(
    cfg: TdxPathsConfig | None = None,
    *,
    override: dict[str, Any] | None = None,
    data_dir: Path | None = None,
) -> EffectivePaths:
    base = cfg or merge_paths_config(paths=override, data_dir=data_dir)
    install = base.install_root
    vipdoc_root = base.vipdoc_root
    if not vipdoc_root and install:
        vipdoc_root = str(Path(install) / "vipdoc")
    if not vipdoc_root:
        vipdoc_root = ""
    hq_cache = base.hq_cache_root
    if not hq_cache and install:
        hq_cache = str(Path(install) / "T0002" / "hq_cache")
    export_dir = base.concept_export_dir
    if not export_dir and install:
        export_dir = str(Path(install) / "T0002" / "export")
    connect = base.connect_cfg_path
    if not connect and install:
        candidate = Path(install) / "connect.cfg"
        if candidate.is_file():
            connect = str(candidate)
    vipdoc = Path(vipdoc_root) if vipdoc_root else None
    sh_lday = str(vipdoc / "sh" / "lday") if vipdoc else None
    sz_lday = str(vipdoc / "sz" / "lday") if vipdoc else None
    sh_min = str(vipdoc / "sh" / "minline") if vipdoc else None
    sz_min = str(vipdoc / "sz" / "minline") if vipdoc else None
    probes: dict[str, Any] = {}
    for name, p in (
        ("connect_cfg", connect),
        ("tdxzs_cfg", str(Path(hq_cache) / "tdxzs.cfg") if hq_cache else None),
        ("block_gn_dat", str(Path(hq_cache) / "block_gn.dat") if hq_cache else None),
    ):
        if not p:
            probes[name] = {"status": "missing", "path": None}
            continue
        path = Path(p)
        if not path.is_file():
            probes[name] = {"status": "missing", "path": str(path)}
        else:
            st = path.stat()
            probes[name] = {
                "status": "ok",
                "path": str(path),
                "size": st.st_size,
                "mtime_ms": int(st.st_mtime * 1000),
            }
    return EffectivePaths(
        install_root=install,
        vipdoc_root=vipdoc_root,
        hq_cache_root=hq_cache,
        concept_export_dir=export_dir,
        connect_cfg_path=connect,
        vipdoc_sh_lday=sh_lday,
        vipdoc_sz_lday=sz_lday,
        vipdoc_sh_minline=sh_min,
        vipdoc_sz_minline=sz_min,
        probes=probes,
    )
