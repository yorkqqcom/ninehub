"""Watch profile config validation and defaults."""

from __future__ import annotations

import re
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import ValidationError

_SYMBOL_RE = re.compile(r"^\d{6}\.(SH|SZ)$")
_RULE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_BASIC_TYPES = frozenset(
    {
        "last_price",
        "pct_change_from_open",
        "pct_change_from_pre_close",
        "pct_change_from_ref",
        "price_velocity",
        "volume_ratio",
        "amplitude",
    }
)
_DIRECTIONS = frozenset({"above", "below"})
_COOLDOWN_MODES = frozenset({"interval", "session"})
_MAX_RULES = 50
_MAX_BINDINGS = 100
_HHMM_RE = re.compile(r"^\d{1,2}:\d{2}$")


def default_config() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "poll_interval_seconds": 10,
        "targets": [],
        "rule_catalog": [],
        "bindings": [],
    }


def normalize_symbol(raw: str) -> str:
    text = str(raw or "").strip().upper()
    if _SYMBOL_RE.match(text):
        return text
    if re.fullmatch(r"\d{6}", text):
        if text.startswith(("5", "6", "9")):
            return f"{text}.SH"
        if text.startswith(("0", "3")):
            return f"{text}.SZ"
    if text.endswith(".BJ") or re.search(r"\.BJ$", text, re.I):
        raise ValidationError("一期不支持北交所盯盘（.BJ）")
    raise ValidationError(f"无效证券代码: {raw}（需 600000.SH / 000001.SZ）")


_CONCEPT_INDEX_RE = re.compile(r"^880\d{3}$")


def normalize_bars_symbol(raw: str) -> str:
    """Symbol for Watch /bars: stock ######.SH/SZ or TDX concept index 880xxx."""
    text = str(raw or "").strip().upper()
    if text.endswith(".TDX"):
        text = text[: -len(".TDX")]
    if _CONCEPT_INDEX_RE.match(text):
        return text
    return normalize_symbol(text)


def _normalize_time_filter(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    out: dict[str, str] = {}
    for key in ("after", "before"):
        val = str(raw.get(key) or "").strip()
        if not val:
            continue
        if not _HHMM_RE.match(val):
            raise ValidationError(f"time_filter.{key} 须为 HH:MM")
        h, m = val.split(":", 1)
        hi, mi = int(h), int(m)
        if hi > 23 or mi > 59:
            raise ValidationError(f"time_filter.{key} 非法时刻")
        out[key] = f"{hi:02d}:{mi:02d}"
    return out or None


def validate_and_normalize_config(raw: dict[str, Any] | None) -> dict[str, Any]:
    settings = get_settings()
    data = dict(raw or {})
    if data.get("include_positions"):
        raise ValidationError("不支持 include_positions")
    cfg = default_config()
    cfg["poll_interval_seconds"] = int(data.get("poll_interval_seconds") or 10)
    if cfg["poll_interval_seconds"] < 3 or cfg["poll_interval_seconds"] > 3600:
        raise ValidationError("poll_interval_seconds 须在 3–3600")

    targets_in = data.get("targets") if isinstance(data.get("targets"), list) else []
    targets: list[dict[str, Any]] = []
    seen_sym: set[str] = set()
    for row in targets_in:
        if not isinstance(row, dict):
            continue
        sym = normalize_symbol(str(row.get("symbol") or ""))
        if sym in seen_sym:
            continue
        seen_sym.add(sym)
        targets.append(
            {
                "symbol": sym,
                "enabled": bool(row.get("enabled", True)),
                "note": str(row.get("note") or "")[:200],
            }
        )
    if len(targets) > settings.watch_max_targets_per_profile:
        raise ValidationError(f"标的数量超过上限 {settings.watch_max_targets_per_profile}")
    cfg["targets"] = targets

    catalog_in = data.get("rule_catalog") if isinstance(data.get("rule_catalog"), list) else []
    if len(catalog_in) > _MAX_RULES:
        raise ValidationError(f"规则数量超过上限 {_MAX_RULES}")
    catalog: list[dict[str, Any]] = []
    ids: set[str] = set()
    for row in catalog_in:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("rule_id") or "")
        if not _RULE_ID_RE.match(rid):
            raise ValidationError(f"无效 rule_id: {rid}")
        if rid in ids:
            raise ValidationError(f"重复 rule_id: {rid}")
        ids.add(rid)
        kind = str(row.get("kind") or "basic")
        cd_mode = str(row.get("cooldown_mode") or "interval").lower()
        if cd_mode not in _COOLDOWN_MODES:
            raise ValidationError(f"无效 cooldown_mode: {cd_mode}")
        try:
            cd_sec = int(row.get("cooldown_seconds") if row.get("cooldown_seconds") is not None else 300)
        except (TypeError, ValueError) as exc:
            raise ValidationError("cooldown_seconds 须为整数") from exc
        if cd_sec < 0 or cd_sec > 86400:
            raise ValidationError("cooldown_seconds 须在 0–86400")
        item: dict[str, Any] = {
            "rule_id": rid,
            "kind": kind,
            "name": str(row.get("name") or rid)[:128],
            "enabled": bool(row.get("enabled", True)),
            "cooldown_seconds": cd_sec,
            "cooldown_mode": cd_mode,
        }
        if kind == "basic":
            cond = row.get("condition") if isinstance(row.get("condition"), dict) else {}
            rtype = str(cond.get("rule_type") or "")
            if rtype == "limit_status":
                raise ValidationError("limit_status 一期不可用")
            if rtype not in _BASIC_TYPES:
                raise ValidationError(f"不支持的 rule_type: {rtype}")
            direction = str(cond.get("direction") or "above").lower()
            if direction not in _DIRECTIONS:
                raise ValidationError(f"无效 direction: {direction}")
            try:
                threshold = float(cond.get("threshold"))
            except (TypeError, ValueError) as exc:
                raise ValidationError("threshold 须为数字") from exc
            item["condition"] = {
                "rule_type": rtype,
                "direction": direction,
                "threshold": threshold,
                "extra_json": cond.get("extra_json") if isinstance(cond.get("extra_json"), dict) else {},
            }
            tf = _normalize_time_filter(row.get("time_filter"))
            if tf:
                item["time_filter"] = tf
        elif kind == "composite":
            children = [str(c) for c in (row.get("children") or [])]
            if len(children) < 2:
                raise ValidationError("composite 至少 2 个子规则")
            item["operator"] = str(row.get("operator") or "and").lower()
            if item["operator"] not in ("and", "or"):
                raise ValidationError("composite operator 须为 and/or")
            item["children"] = children
            item["time_filter"] = _normalize_time_filter(row.get("time_filter"))
            item["suppress_child_independent_when_composite"] = bool(
                row.get("suppress_child_independent_when_composite")
            )
        else:
            raise ValidationError(f"未知 kind: {kind}")
        catalog.append(item)

    # children must reference basic rules
    basic_ids = {r["rule_id"] for r in catalog if r["kind"] == "basic"}
    for r in catalog:
        if r["kind"] != "composite":
            continue
        for cid in r["children"]:
            if cid not in basic_ids:
                raise ValidationError(f"composite 子规则必须是 basic: {cid}")

    cfg["rule_catalog"] = catalog

    bindings_in = data.get("bindings") if isinstance(data.get("bindings"), list) else []
    if len(bindings_in) > _MAX_BINDINGS:
        raise ValidationError(f"binding 数量超过上限 {_MAX_BINDINGS}")
    bindings: list[dict[str, Any]] = []
    rule_ids = {r["rule_id"] for r in catalog}
    for row in bindings_in:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("rule_id") or "")
        if rid not in rule_ids:
            raise ValidationError(f"binding 引用不存在的 rule_id: {rid}")
        scope = row.get("scope") if isinstance(row.get("scope"), dict) else {"type": "targets"}
        st = str(scope.get("type") or "targets")
        if st == "positions":
            raise ValidationError("不支持 scope.type=positions")
        if st not in ("targets", "symbols"):
            raise ValidationError(f"无效 scope.type: {st}")
        scope_out: dict[str, Any] = {"type": st}
        if st == "symbols":
            scope_out["symbols"] = [normalize_symbol(s) for s in (scope.get("symbols") or [])]
        bindings.append(
            {
                "binding_id": str(row.get("binding_id") or f"b_{rid}")[:64],
                "rule_id": rid,
                "scope": scope_out,
                "enabled": bool(row.get("enabled", True)),
            }
        )
    cfg["bindings"] = bindings
    return cfg
