"""Watch (盯盘) API + WebSocket."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_async_session
from app.core.deps import get_current_user
from app.core.security import decode_access_token
from app.models.user import User
from app.models.watch import WatchAlertEvent, WatchProfile
from app.schemas.watch import (
    AlertListOut,
    AlertOut,
    ConfigPutBody,
    SetEnabledBody,
    WatchProfileCreate,
    WatchProfileOut,
)
from app.services.watch.engine import collect_watched_symbols
from app.services.watch.hub import get_quote_hub
from app.services.watch.service import WatchProfileService
from app.services.watch.sidecar_client import SidecarTransportError, bars_date_window, get_sidecar_client
from app.services.watch.ticker import get_watch_ticker
from app.services.watch.types import QuoteSnap
from app.services.watch.ws_auth import token_from_ws_protocols

_CONCEPT_RE = re.compile(r"^880\d{3}$")
_BARS_PERIODS = frozenset({"1m", "1d"})

logger = logging.getLogger(__name__)
router = APIRouter()
_svc = WatchProfileService()
_ws_conn_counts: dict[int, int] = {}
_WS_MAX_PER_USER = 3

_QUOTE_ITEM_KEYS = frozenset(
    {
        "symbol",
        "last_price",
        "open",
        "pre_close",
        "high",
        "low",
        "volume",
        "amount",
        "change_pct",
        "ts_ms",
        "stale",
        "age_seconds",
        "degraded",
        "name",
    }
)


def _quote_item(snap: QuoteSnap) -> dict[str, Any]:
    """Serialize QuoteSnap for HTTP /quotes and WS /stream (field parity)."""
    return {
        "symbol": snap.symbol,
        "last_price": snap.last_price,
        "open": snap.open,
        "pre_close": snap.pre_close,
        "high": snap.high,
        "low": snap.low,
        "volume": snap.volume,
        "amount": snap.amount,
        "change_pct": snap.change_pct,
        "ts_ms": snap.ts_ms,
        "stale": snap.stale,
        "age_seconds": snap.age_seconds,
        "degraded": snap.degraded,
        "name": snap.name,
    }


async def _user_from_token(session: AsyncSession, token: str) -> User | None:
    payload = decode_access_token(token)
    if payload is None or "sub" not in payload:
        return None
    result = await session.execute(select(User).where(User.username == payload["sub"]))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


@router.post("/profiles/ensure-default", response_model=WatchProfileOut, summary="确保默认盯盘配置")
async def ensure_default(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> WatchProfile:
    return await _svc.ensure_default(session, user.id)


@router.get("/profiles", response_model=list[WatchProfileOut], summary="盯盘配置列表")
async def list_profiles(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> list[WatchProfile]:
    await _svc.ensure_default(session, user.id)
    return await _svc.list_profiles(session, user.id)


@router.post("/profiles", response_model=WatchProfileOut, summary="创建盯盘配置")
async def create_profile(
    body: WatchProfileCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> WatchProfile:
    return await _svc.create(session, user.id, name=body.name, config=body.config_json)


@router.get("/profiles/{profile_id}", response_model=WatchProfileOut, summary="盯盘配置详情")
async def get_profile(
    profile_id: int,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> WatchProfile:
    return await _svc.get_owned(session, user.id, profile_id)


@router.delete("/profiles/{profile_id}", summary="删除盯盘配置")
async def delete_profile(
    profile_id: int,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict[str, str]:
    await _svc.delete(session, user.id, profile_id)
    return {"status": "ok"}


@router.post("/profiles/{profile_id}/set-enabled", response_model=WatchProfileOut, summary="启用/关闭盯盘")
async def set_enabled(
    profile_id: int,
    body: SetEnabledBody,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> WatchProfile:
    return await _svc.set_enabled(session, user.id, profile_id, body.enabled)


@router.get("/profiles/{profile_id}/config", summary="获取 config")
async def get_config(
    profile_id: int,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict[str, Any]:
    row = await _svc.get_owned(session, user.id, profile_id)
    return {"config_revision": row.config_revision, "config_json": row.config_json}


@router.put("/profiles/{profile_id}/config", response_model=WatchProfileOut, summary="整包更新 config")
async def put_config(
    profile_id: int,
    body: ConfigPutBody,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> WatchProfile:
    return await _svc.put_config(
        session,
        user.id,
        profile_id,
        config=body.config_json,
        expected_revision=body.expected_revision,
    )


@router.post("/profiles/{profile_id}/clear-cooldown", summary="清除冷却")
async def clear_cooldown(
    profile_id: int,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict[str, str]:
    await _svc.clear_cooldown(session, user.id, profile_id)
    return {"status": "ok"}


@router.get("/alerts", response_model=AlertListOut, summary="告警列表")
async def list_alerts(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> AlertListOut:
    from datetime import datetime, timedelta, timezone

    from app.core.config import get_settings

    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.watch_alert_retention_days)
    total = (
        await session.execute(
            select(func.count())
            .select_from(WatchAlertEvent)
            .where(WatchAlertEvent.user_id == user.id, WatchAlertEvent.created_at >= cutoff)
        )
    ).scalar_one()
    result = await session.execute(
        select(WatchAlertEvent)
        .where(WatchAlertEvent.user_id == user.id, WatchAlertEvent.created_at >= cutoff)
        .order_by(WatchAlertEvent.id.desc())
        .offset(skip)
        .limit(limit)
    )
    items = list(result.scalars().all())
    page = (skip // limit) + 1 if limit else 1
    return AlertListOut(
        items=[AlertOut.model_validate(i) for i in items],
        total=int(total),
        page=page,
        size=limit,
    )


@router.get("/quotes", summary="批量行情（读 cache，可 stale）")
async def get_quotes(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
    symbols: str = Query("", description="逗号分隔代码，空则用启用配置标的"),
) -> dict[str, Any]:
    from app.services.watch.config import normalize_symbol
    from app.core.exceptions import ValidationError as AppValidationError

    syms: list[str] = []
    if symbols.strip():
        for raw in symbols.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                syms.append(normalize_symbol(raw))
            except AppValidationError:
                continue
        # preserve order, drop dups
        seen: set[str] = set()
        ordered: list[str] = []
        for s in syms:
            if s not in seen:
                seen.add(s)
                ordered.append(s)
        syms = ordered
    else:
        profiles = await _svc.list_profiles(session, user.id)
        for p in profiles:
            if p.enabled:
                syms.extend(collect_watched_symbols(dict(p.config_json or {})))
        syms = sorted(set(syms))
    hub = get_quote_hub()
    if syms:
        batch = await asyncio.to_thread(hub.get_or_refresh, syms)
    else:
        batch = hub.get_cached(None)
    snaps = (
        list(batch.items.values())
        if not syms
        else [batch.items[x] for x in syms if x in batch.items]
    )
    return {
        "items": [_quote_item(s) for s in snaps],
        "stale": batch.stale,
        "degraded": batch.degraded,
        "message": batch.message,
    }


@router.get("/engine-status", summary="盯盘引擎状态")
async def engine_status(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> dict[str, Any]:
    _ = user
    enabled_count = (
        await session.execute(
            select(func.count()).select_from(WatchProfile).where(WatchProfile.enabled.is_(True))
        )
    ).scalar_one()
    st = get_watch_ticker().status
    st["enabled_profile_count"] = int(enabled_count)
    st["sidecar_ok"] = not bool(st.get("last_error"))
    return st


@router.get("/ranks", summary="行情榜快照（概念+自选车道）")
async def get_ranks(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_async_session)],
    concept: str | None = Query(None, description="概念裸码 880xxx；省略/空则成分清空"),
    top_n: int = Query(30, ge=1, le=30),
) -> JSONResponse:
    """Inject enabled-profile pool into Sidecar ranks snapshot."""
    profiles = await _svc.list_profiles(session, user.id)
    pool: list[str] = []
    seen: set[str] = set()
    for p in profiles:
        if not p.enabled:
            continue
        for s in collect_watched_symbols(dict(p.config_json or {})):
            if s not in seen:
                seen.add(s)
                pool.append(s)

    concept_code: str | None = None
    if concept is not None and str(concept).strip():
        raw = str(concept).strip().upper()
        if raw.endswith(".TDX"):
            raw = raw[: -len(".TDX")]
        if not _CONCEPT_RE.match(raw):
            raise HTTPException(status_code=400, detail="concept must be 880xxx")
        concept_code = raw

    client = get_sidecar_client()
    try:
        payload = await asyncio.to_thread(
            client.fetch_ranks_snapshot,
            pool_symbols=pool,
            concept_code=concept_code,
            top_n=top_n,
        )
    except SidecarTransportError as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "sidecar ranks unavailable") from exc
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@router.get("/bars", summary="选中标的 K 线（股票或概念指数 880）")
async def get_bars(
    user: Annotated[User, Depends(get_current_user)],
    symbol: str = Query(..., description="600000.SH / 000001.SZ / 880xxx"),
    period: str = Query("1m", description="1m | 1d"),
) -> JSONResponse:
    """Proxy Sidecar bars/batch for stocks or TDX concept indices."""
    _ = user
    from app.core.exceptions import ValidationError as AppValidationError
    from app.services.watch.config import normalize_bars_symbol

    period_norm = str(period or "").strip().lower()
    if period_norm not in _BARS_PERIODS:
        raise HTTPException(status_code=400, detail="period must be 1m or 1d")

    try:
        sym = normalize_bars_symbol(symbol)
    except AppValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    start_d, end_d = bars_date_window(period_norm)
    client = get_sidecar_client()
    try:
        payload = await asyncio.to_thread(
            client.fetch_bars,
            symbol=sym,
            period=period_norm,
            start_date=start_d,
            end_date=end_d,
        )
    except SidecarTransportError as exc:
        raise HTTPException(status_code=502, detail=str(exc) or "sidecar bars unavailable") from exc
    return JSONResponse(
        content=jsonable_encoder(payload),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@router.websocket("/stream")
async def watch_stream(websocket: WebSocket) -> None:
    # Prefer subprotocol token, then first-frame auth; query token is last resort (logs).
    token = token_from_ws_protocols(websocket.headers)
    accept_kwargs: dict[str, Any] = {}
    raw_proto = (websocket.headers.get("sec-websocket-protocol") or "").strip()
    if raw_proto and token:
        accept_kwargs["subprotocol"] = raw_proto.split(",")[0].strip()
    await websocket.accept(**accept_kwargs)

    used_query_token = False
    if not token:
        token = (websocket.query_params.get("token") or "").strip()
        used_query_token = bool(token)
    try:
        if not token:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
            msg = json.loads(raw)
            if isinstance(msg, dict) and msg.get("type") == "auth":
                token = str(msg.get("token") or "")
    except Exception:  # noqa: BLE001
        await websocket.close(code=4401)
        return

    if used_query_token:
        logger.warning("watch ws auth via query token (prefer Sec-WebSocket-Protocol)")

    async with AsyncSessionLocal() as session:
        user = await _user_from_token(session, token)
        if user is None:
            await websocket.close(code=4401)
            return
        user_id = user.id

    if _ws_conn_counts.get(user_id, 0) >= _WS_MAX_PER_USER:
        await websocket.close(code=4408)
        return
    _ws_conn_counts[user_id] = _ws_conn_counts.get(user_id, 0) + 1

    hub = get_quote_hub()
    loops = 0
    try:
        while True:
            loops += 1
            if loops % 30 == 0:
                async with AsyncSessionLocal() as session:
                    user = await _user_from_token(session, token)
                    if user is None:
                        await websocket.close(code=4401)
                        return

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(WatchProfile).where(
                        WatchProfile.user_id == user_id, WatchProfile.enabled.is_(True)
                    )
                )
                profiles = list(result.scalars().all())
                syms: list[str] = []
                for p in profiles:
                    syms.extend(collect_watched_symbols(dict(p.config_json or {})))
                syms = sorted(set(syms))

            batch = hub.get_cached(syms)
            if syms and (batch.stale or any(s not in batch.items for s in syms)):
                batch = await asyncio.to_thread(hub.get_or_refresh, syms)
            payload = {
                "type": "quotes",
                "stale": batch.stale,
                "degraded": batch.degraded,
                "message": batch.message,
                "config_epoch": hub.config_epoch,
                "items": [_quote_item(batch.items[s]) for s in syms if s in batch.items],
            }
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))
            await asyncio.sleep(2.0)
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        logger.debug("watch ws closed: %s", exc)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
    finally:
        _ws_conn_counts[user_id] = max(0, _ws_conn_counts.get(user_id, 1) - 1)
        if _ws_conn_counts.get(user_id) == 0:
            _ws_conn_counts.pop(user_id, None)
