"""WatchTicker: lifespan background loop."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import select

from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.watch import WatchAlertEvent, WatchCooldownState, WatchProfile
from app.services.watch.alert_notify import (
    is_watch_alert_webhook_configured,
    notify_quote_alert,
    snapshot_from_event,
)
from app.services.watch.cooldown import cooldown_active, mark_cooldown
from app.services.watch.engine import (
    collect_watched_symbols,
    evaluate_profile_rules,
    feed_quote_windows,
)
from app.services.watch.hours import is_watch_session_open, session_trade_date
from app.services.watch.hub import get_quote_hub
from app.services.watch.leader_lock import LeaderLock
from app.services.watch.provider import LocalPytdxQuoteProvider, TdxSidecarQuoteProvider
from app.services.watch.window import WindowStore

logger = logging.getLogger(__name__)


class WatchTicker:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._started = False
        self._running = False
        self._leader: LeaderLock | None = None
        self._leader_held = False
        self._redis_ok = False
        self._windows = WindowStore()
        self._last_tick_at: float | None = None
        self._last_error: str = ""
        self._off_hours = False
        self._degraded_throttle: dict[int, float] = {}
        self._last_poll_at: dict[int, float] = {}
        self._notify_tasks: set[asyncio.Task[None]] = set()

    @property
    def status(self) -> dict[str, Any]:
        hub = get_quote_hub().status()
        return {
            "ticker_running": self._running,
            "leader_held": self._leader_held,
            "redis_ok": self._redis_ok,
            "last_tick_at": self._last_tick_at,
            "last_error": self._last_error or hub.get("last_error"),
            "off_hours": self._off_hours,
            **hub,
        }

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        settings = get_settings()
        self._leader = LeaderLock(settings.redis_url)
        hub = get_quote_hub()

        def _get(symbols: list[str]):
            primary = TdxSidecarQuoteProvider()
            batch = primary.get_quotes(symbols)
            usable = any(
                s.last_price is not None and float(s.last_price) > 0 and not s.degraded
                for s in batch.items.values()
            )
            # Sidecar unreachable OR returned only unusable rows → in-process pytdx
            if batch.degraded and not usable:
                return LocalPytdxQuoteProvider().get_quotes(symbols)
            return batch

        hub.set_provider(_get)
        self._task = asyncio.create_task(self._run(), name="watch-ticker")
        acquired = self._leader.try_acquire() if self._leader else False
        self._leader_held = acquired
        self._redis_ok = bool(self._leader and self._leader.ping())
        logger.info(
            "watch_ticker starting require_redis_leader=%s workers_hint=1 leader_acquired=%s redis_ok=%s",
            settings.watch_require_redis_leader,
            acquired,
            self._redis_ok,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._leader:
            self._leader.release()
        self._started = False
        logger.info("watch_ticker stopped")

    def _schedule_notify(self, snapshot: dict[str, Any]) -> None:
        # Avoid create_task noise when outbound webhook is not configured (url+secret pair).
        if not is_watch_alert_webhook_configured():
            return
        alert_id = snapshot.get("alert_id")
        task = asyncio.create_task(
            notify_quote_alert(snapshot),
            name=f"watch-notify-{alert_id}",
        )
        self._notify_tasks.add(task)
        task.add_done_callback(self._notify_tasks.discard)

    async def _run(self) -> None:
        self._running = True
        settings = get_settings()
        while self._running:
            try:
                await self._tick_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                logger.exception("watch ticker tick failed: %s", exc)
            await asyncio.sleep(float(settings.watch_tick_interval_seconds))

    async def _tick_once(self) -> None:
        settings = get_settings()
        self._redis_ok = bool(self._leader and self._leader.ping())
        acquired = False
        if self._leader:
            acquired = self._leader.renew() if self._leader_held else self._leader.try_acquire()
        self._leader_held = acquired

        if not acquired:
            if settings.watch_require_redis_leader:
                logger.debug("watch ticker standby (no leader)")
                return
            if not self._redis_ok:
                logger.warning("watch ticker running without redis leader lock")

        open_ok, reason = is_watch_session_open()
        self._off_hours = not open_ok
        if not open_ok:
            self._last_tick_at = time.time()
            return

        trade_date = session_trade_date()
        tick_degraded = False
        tick_message = ""
        pending_notify: list[dict[str, Any]] = []

        async with AsyncSessionLocal() as session:
            result = await session.execute(select(WatchProfile).where(WatchProfile.enabled.is_(True)))
            profiles = list(result.scalars().all())
            active_ids = {p.id for p in profiles}
            self._last_poll_at = {k: v for k, v in self._last_poll_at.items() if k in active_ids}
            self._degraded_throttle = {
                k: v for k, v in self._degraded_throttle.items() if k in active_ids
            }

            wanted_board: set[str] = set()
            snapshots: list[tuple[WatchProfile, dict]] = []
            now = time.time()
            for p in profiles:
                cfg = dict(p.config_json or {})
                # Always keep board symbols warm even when this profile is not due for alert eval
                symbols = collect_watched_symbols(cfg)
                wanted_board.update(symbols)
                poll = max(3, int(cfg.get("poll_interval_seconds") or 10))
                last = self._last_poll_at.get(p.id, 0)
                if now - last < poll:
                    continue
                self._last_poll_at[p.id] = now
                snapshots.append((p, cfg))

            hub = get_quote_hub()
            hub.set_wanted_symbols(wanted_board)
            self._windows.retain(wanted_board)
            if not wanted_board:
                self._last_tick_at = time.time()
                return

            batch = await asyncio.to_thread(hub.refresh, sorted(wanted_board))
            quotes = {s: batch.items[s] for s in wanted_board if s in batch.items}
            tick_degraded = bool(batch.degraded)
            tick_message = batch.message or ""

            # Keep velocity/volume windows warm even when profile alert poll is throttled
            feed_quote_windows(quotes=quotes, windows=self._windows, trade_date=trade_date)

            new_quote_alerts: list[WatchAlertEvent] = []
            for p, cfg in snapshots:
                hits = evaluate_profile_rules(
                    config=cfg,
                    quotes=quotes,
                    windows=self._windows,
                    trade_date=trade_date,
                )

                # degraded throttle
                missing = [s for s in collect_watched_symbols(cfg) if s not in quotes or quotes[s].degraded]
                if missing and batch.degraded:
                    last_deg = self._degraded_throttle.get(p.id, 0)
                    if now - last_deg >= 60:
                        self._degraded_throttle[p.id] = now
                        session.add(
                            WatchAlertEvent(
                                profile_id=p.id,
                                user_id=p.user_id,
                                symbol="",
                                rule_id="",
                                event_type="watch_degraded",
                                payload_json={"missing": missing[:20], "message": batch.message},
                            )
                        )

                cd_row = (
                    await session.execute(
                        select(WatchCooldownState)
                        .where(WatchCooldownState.profile_id == p.id)
                        .with_for_update()
                    )
                ).scalar_one_or_none()
                state = dict((cd_row.state_json if cd_row else None) or {})
                catalog = {
                    str(r.get("rule_id")): r
                    for r in (cfg.get("rule_catalog") or [])
                    if isinstance(r, dict)
                }
                changed = False
                for hit in hits:
                    rule = catalog.get(hit.rule_id) or {}
                    cd_sec = int(rule.get("cooldown_seconds") or 300)
                    cd_mode = str(rule.get("cooldown_mode") or "interval")
                    if cooldown_active(
                        state,
                        rule_id=hit.rule_id,
                        symbol=hit.symbol,
                        cooldown_seconds=cd_sec,
                        cooldown_mode=cd_mode,
                        trade_date=trade_date,
                    ):
                        continue
                    ev = WatchAlertEvent(
                        profile_id=p.id,
                        user_id=p.user_id,
                        symbol=hit.symbol,
                        rule_id=hit.rule_id,
                        event_type="quote_alert",
                        payload_json={
                            "metric": hit.metric,
                            "metric_value": hit.metric_value,
                            "threshold": hit.threshold,
                            "message": hit.message,
                            "last_price": hit.last_price,
                            "rule_kind": hit.rule_kind,
                            "rule_name": hit.rule_name,
                        },
                    )
                    session.add(ev)
                    new_quote_alerts.append(ev)
                    state = mark_cooldown(
                        state, rule_id=hit.rule_id, symbol=hit.symbol, trade_date=trade_date
                    )
                    changed = True
                if changed:
                    if cd_row is None:
                        session.add(WatchCooldownState(profile_id=p.id, state_json=state))
                    else:
                        cd_row.state_json = state
                        flag_modified(cd_row, "state_json")

            if new_quote_alerts:
                await session.flush()
                for ev in new_quote_alerts:
                    snap = snapshot_from_event(ev)
                    if snap is not None:
                        pending_notify.append(snap)

            await session.commit()

        for item in pending_notify:
            self._schedule_notify(item)

        self._last_tick_at = time.time()
        if tick_degraded:
            self._last_error = tick_message or self._last_error or "quotes degraded"
        else:
            self._last_error = ""
        _ = reason


_ticker: WatchTicker | None = None


def get_watch_ticker() -> WatchTicker:
    global _ticker
    if _ticker is None:
        _ticker = WatchTicker()
    return _ticker
