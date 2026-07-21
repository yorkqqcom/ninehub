"""Rule evaluation (basic + one-level composite). Stale snaps never alert."""

from __future__ import annotations

import time
from typing import Any

from app.services.watch.types import AlertHit, QuoteSnap
from app.services.watch.window import WindowStore

_MIN = 1e-6
_ENABLED_RULES = frozenset(
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


def _dir_ok(direction: str, value: float, threshold: float) -> bool:
    d = str(direction or "").lower()
    if d == "above":
        return value >= threshold
    if d == "below":
        return value <= threshold
    return False


def _hhmm_active(time_filter: dict[str, Any] | None, *, now_ms: int | None = None) -> bool:
    if not time_filter:
        return True
    from datetime import datetime
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    if now_ms:
        now = datetime.fromtimestamp(now_ms / 1000.0, tz=ZoneInfo("Asia/Shanghai"))
    minutes = now.hour * 60 + now.minute

    def parse(s: Any) -> int | None:
        text = str(s or "").strip()
        if not text or ":" not in text:
            return None
        h, m = text.split(":", 1)
        try:
            return int(h) * 60 + int(m)
        except ValueError:
            return None

    after = parse(time_filter.get("after"))
    before = parse(time_filter.get("before"))
    if after is not None and minutes < after:
        return False
    if before is not None and minutes > before:
        return False
    return True


def evaluate_basic(
    *,
    symbol: str,
    snap: QuoteSnap,
    condition: dict[str, Any],
    windows: WindowStore,
    rule_id: str = "",
    rule_name: str = "",
) -> AlertHit | None:
    if not snap.usable_for_alert():
        return None
    rtype = str(condition.get("rule_type") or "")
    if rtype not in _ENABLED_RULES:
        return None
    direction = str(condition.get("direction") or "")
    try:
        threshold = float(condition.get("threshold"))
    except (TypeError, ValueError):
        return None
    extra = condition.get("extra_json") if isinstance(condition.get("extra_json"), dict) else {}
    last = float(snap.last_price or 0)
    open_px = float(snap.open or 0) if snap.open else 0.0
    pre = float(snap.pre_close or 0) if snap.pre_close else 0.0
    high = float(snap.high or 0) if snap.high else 0.0
    low = float(snap.low or 0) if snap.low else 0.0
    now_ms = int(snap.ts_ms or time.time() * 1000)
    ws = windows.get(symbol)

    metric = ""
    metric_value = 0.0
    ok = False

    if rtype == "last_price":
        metric, metric_value = "last_price", last
        ok = _dir_ok(direction, last, threshold)
    elif rtype == "pct_change_from_open":
        if open_px <= _MIN:
            return None
        metric_value = (last - open_px) / open_px
        metric, ok = "pct_from_open", _dir_ok(direction, metric_value, threshold)
    elif rtype == "pct_change_from_pre_close":
        if pre <= _MIN:
            return None
        metric_value = (last - pre) / pre
        metric, ok = "pct_from_pre_close", _dir_ok(direction, metric_value, threshold)
    elif rtype == "pct_change_from_ref":
        try:
            ref = float(extra.get("ref_price"))
        except (TypeError, ValueError):
            return None
        if ref <= _MIN:
            return None
        metric_value = (last - ref) / ref
        metric, ok = "pct_from_ref", _dir_ok(direction, metric_value, threshold)
    elif rtype == "amplitude":
        if high <= _MIN or low <= _MIN or pre <= _MIN or high < low:
            return None
        metric_value = (high - low) / pre
        metric, ok = "amplitude", _dir_ok(direction, metric_value, threshold)
    elif rtype == "price_velocity":
        win = int(extra.get("window_seconds") or 60)
        ratio = ws.price_velocity(win, now_ms)
        if ratio is None:
            return None
        metric_value = ratio
        metric, ok = "price_velocity", _dir_ok(direction, ratio, threshold)
    elif rtype == "volume_ratio":
        win = int(extra.get("volume_window_seconds") or 60)
        ratio = ws.volume_ratio_delta(win, now_ms)
        if ratio is None:
            return None
        metric_value = ratio
        metric, ok = "volume_ratio", _dir_ok(direction, ratio, threshold)
    else:
        return None

    if not ok:
        return None
    return AlertHit(
        rule_id=rule_id,
        symbol=symbol,
        metric=metric,
        metric_value=metric_value,
        threshold=threshold,
        message=f"{symbol} {rule_name or rule_id} {metric}={metric_value:.4f}",
        last_price=last,
        rule_kind="basic",
        rule_name=rule_name,
    )


def evaluate_profile_rules(
    *,
    config: dict[str, Any],
    quotes: dict[str, QuoteSnap],
    windows: WindowStore,
    trade_date: str,
) -> list[AlertHit]:
    """Evaluate bindings against targets/symbols scopes. No positions.

    Caller must feed rolling windows (feed_quote_windows) before evaluate when
    velocity/volume rules need history; WatchTicker does this every tick.
    """
    _ = trade_date
    targets = config.get("targets") if isinstance(config.get("targets"), list) else []
    catalog = {str(r.get("rule_id")): r for r in (config.get("rule_catalog") or []) if isinstance(r, dict)}
    bindings = config.get("bindings") if isinstance(config.get("bindings"), list) else []

    enabled_targets = {
        str(t.get("symbol")).upper()
        for t in targets
        if isinstance(t, dict) and t.get("enabled", True) and t.get("symbol")
    }

    hits: list[AlertHit] = []
    basic_hits: list[AlertHit] = []
    composite_hits: list[AlertHit] = []

    for binding in bindings:
        if not isinstance(binding, dict) or not binding.get("enabled", True):
            continue
        rule_id = str(binding.get("rule_id") or "")
        rule = catalog.get(rule_id)
        if not rule or not rule.get("enabled", True):
            continue
        scope = binding.get("scope") if isinstance(binding.get("scope"), dict) else {}
        scope_type = str(scope.get("type") or "targets")
        if scope_type == "positions":
            continue
        if scope_type == "symbols":
            symbols = {
                str(s).upper()
                for s in (scope.get("symbols") or [])
                if str(s).upper().endswith((".SH", ".SZ"))
            }
        else:
            symbols = set(enabled_targets)

        kind = str(rule.get("kind") or "basic")
        name = str(rule.get("name") or rule_id)
        if not _hhmm_active(rule.get("time_filter") if isinstance(rule.get("time_filter"), dict) else None):
            continue

        if kind == "basic":
            cond = rule.get("condition") if isinstance(rule.get("condition"), dict) else {}
            for sym in symbols:
                snap = quotes.get(sym)
                if not snap:
                    continue
                hit = evaluate_basic(
                    symbol=sym,
                    snap=snap,
                    condition=cond,
                    windows=windows,
                    rule_id=rule_id,
                    rule_name=name,
                )
                if hit:
                    basic_hits.append(hit)
        elif kind == "composite":
            children = [str(c) for c in (rule.get("children") or [])]
            op = str(rule.get("operator") or "and").lower()
            for sym in symbols:
                snap = quotes.get(sym)
                if not snap or not snap.usable_for_alert():
                    continue
                child_ok: list[bool] = []
                for cid in children:
                    child = catalog.get(cid)
                    if not child or str(child.get("kind")) != "basic":
                        child_ok.append(False)
                        continue
                    cond = child.get("condition") if isinstance(child.get("condition"), dict) else {}
                    hit = evaluate_basic(
                        symbol=sym,
                        snap=snap,
                        condition=cond,
                        windows=windows,
                        rule_id=cid,
                        rule_name=str(child.get("name") or cid),
                    )
                    child_ok.append(hit is not None)
                passed = all(child_ok) if op == "and" else any(child_ok)
                if passed and child_ok:
                    composite_hits.append(
                        AlertHit(
                            rule_id=rule_id,
                            symbol=sym,
                            metric="composite",
                            metric_value=1.0,
                            threshold=1.0,
                            message=f"{sym} composite {name}",
                            last_price=float(snap.last_price or 0),
                            rule_kind="composite",
                            rule_name=name,
                            child_rule_ids=children,
                        )
                    )

    # suppress child independent when composite fires
    suppress: dict[str, set[str]] = {}
    for hit in composite_hits:
        rule = catalog.get(hit.rule_id) or {}
        if rule.get("suppress_child_independent_when_composite"):
            suppress.setdefault(hit.symbol, set()).update(hit.child_rule_ids or [])

    for hit in basic_hits:
        if hit.rule_id in suppress.get(hit.symbol, set()):
            continue
        hits.append(hit)
    hits.extend(composite_hits)
    return hits


def feed_quote_windows(
    *,
    quotes: dict[str, QuoteSnap],
    windows: WindowStore,
    trade_date: str,
) -> None:
    """Push fresh usable quotes into rolling windows. Call every tick, not only on alert eval."""
    for sym, snap in quotes.items():
        if snap.stale or snap.degraded:
            continue
        if snap.last_price and snap.last_price > 0:
            windows.get(sym).push(
                ts_ms=int(snap.ts_ms or time.time() * 1000),
                last_price=float(snap.last_price),
                volume=snap.volume,
                trade_date=trade_date,
            )


def collect_target_symbols(config: dict[str, Any]) -> list[str]:
    """Enabled targets only (board default when no symbol-scope bindings)."""
    targets = config.get("targets") if isinstance(config.get("targets"), list) else []
    out: list[str] = []
    seen: set[str] = set()
    for t in targets:
        if not isinstance(t, dict) or not t.get("enabled", True):
            continue
        sym = str(t.get("symbol") or "").upper()
        if sym.endswith((".SH", ".SZ")) and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def collect_watched_symbols(config: dict[str, Any]) -> list[str]:
    """Symbols to keep warm: enabled targets + symbols-scope bindings."""
    out = collect_target_symbols(config)
    seen = set(out)
    bindings = config.get("bindings") if isinstance(config.get("bindings"), list) else []
    for binding in bindings:
        if not isinstance(binding, dict) or not binding.get("enabled", True):
            continue
        scope = binding.get("scope") if isinstance(binding.get("scope"), dict) else {}
        if str(scope.get("type") or "") != "symbols":
            continue
        for raw in scope.get("symbols") or []:
            sym = str(raw or "").upper()
            if sym.endswith((".SH", ".SZ")) and sym not in seen:
                seen.add(sym)
                out.append(sym)
    return out
