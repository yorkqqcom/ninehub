"""Backtest application service: validate, enqueue, authorize results."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.registry import get_data_type_entry
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models.browser import BrowserWatchlist
from app.models.platform_job import PlatformJob
from app.models.user import User
from app.services.platform.job_service import PlatformJobService
from app.services.research.constants import (
    JOB_TYPE,
    MAX_UNIVERSE,
    MAX_YEARS,
    SYMBOL_RE,
    TRADE_PREVIEW_LIMIT,
)
from app.services.research.runner import BacktestRunner
from app.services.research.signals import SIGNAL_REGISTRY, list_signal_defs, normalize_signal_params

MAX_FEE_BPS = 500.0
STALE_JOB_MINUTES = 90


def _require_finite_fee(value: Any, *, field: str, default: float = 5.0) -> float:
    if value is None:
        return default
    try:
        fee = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field} 无效", details={"code": "BACKTEST_FEE"}) from exc
    if not math.isfinite(fee):
        raise ValidationError(f"{field} 无效", details={"code": "BACKTEST_FEE"})
    if fee < 0:
        raise ValidationError("费用/滑点不能为负", details={"code": "BACKTEST_FEE"})
    if fee > MAX_FEE_BPS:
        raise ValidationError(
            f"费用/滑点不得超过 {MAX_FEE_BPS:g} bps",
            details={"code": "BACKTEST_FEE"},
        )
    return fee


class BacktestService:
    def __init__(self) -> None:
        self._jobs = PlatformJobService()
        self._runner = BacktestRunner()

    def list_signals(self) -> list[dict[str, Any]]:
        return list_signal_defs()

    async def enqueue(
        self,
        session: AsyncSession,
        user: User,
        body: dict[str, Any],
    ) -> PlatformJob:
        await self._assert_no_running(session, user.id)

        codes = await self._resolve_codes(session, user, body)
        start = self._parse_date(body.get("start_date"), "start_date")
        end = self._parse_date(body.get("end_date"), "end_date")
        if end < start:
            raise ValidationError("结束日早于开始日", details={"code": "BACKTEST_DATE_RANGE"})
        if (end - start).days > MAX_YEARS * 366:
            raise ValidationError(
                f"回测区间不得超过 {MAX_YEARS} 年",
                details={"code": "BACKTEST_RANGE_LIMIT"},
            )

        signal_id = str(body.get("signal_id") or "")
        if signal_id not in SIGNAL_REGISTRY:
            raise ValidationError("未知信号", details={"code": "BACKTEST_SIGNAL"})

        adjust = str(body.get("adjust") or "qfq")
        if adjust not in ("qfq", "hfq", "none"):
            raise ValidationError("复权参数无效", details={"code": "BACKTEST_ADJUST"})

        await self._assert_backtest_data(session, start, end, adjust=adjust)

        try:
            params = normalize_signal_params(signal_id, dict(body.get("params") or {}))
        except KeyError as exc:
            raise ValidationError("未知信号", details={"code": "BACKTEST_SIGNAL"}) from exc

        commission_bps = _require_finite_fee(body.get("commission_bps"), field="commission_bps")
        slippage_bps = _require_finite_fee(body.get("slippage_bps"), field="slippage_bps")
        max_positions = int(body.get("max_positions") if body.get("max_positions") is not None else 5)
        if max_positions < 1 or max_positions > MAX_UNIVERSE:
            raise ValidationError("max_positions 无效", details={"code": "BACKTEST_MAX_POS"})

        job = await self._jobs.create(session, job_type=JOB_TYPE, created_by_id=user.id)
        payload = {
            "codes": codes,
            "watchlist_id": body.get("watchlist_id"),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "signal_id": signal_id,
            "params": params,
            "adjust": adjust,
            "commission_bps": commission_bps,
            "slippage_bps": slippage_bps,
            "max_positions": max_positions,
            "universe_size": len(codes),
        }
        await self._jobs.update(
            session,
            job.id,
            message="backtest queued",
            result_json={"params": payload},
        )
        await session.commit()

        from app.tasks.backtest_tasks import run_backtest_task
        from app.tasks.dispatch import dispatch_task

        try:
            dispatch_task(run_backtest_task, job.id)
        except Exception as exc:
            await self._jobs.update(
                session,
                job.id,
                status="failed",
                progress=100,
                message="dispatch failed",
                error=str(exc),
            )
            await session.commit()
            raise ValidationError(
                "回测任务入队失败",
                details={"code": "BACKTEST_DISPATCH", "error": str(exc)},
            ) from exc
        return job

    async def get_result(
        self,
        session: AsyncSession,
        user: User,
        job_id: int,
    ) -> dict[str, Any]:
        job = await self._authorize_job(session, user, job_id)
        if job.status != "success":
            raise ValidationError(
                f"任务未完成: {job.status}",
                details={"code": "BACKTEST_NOT_READY", "status": job.status},
            )
        data = self._runner.read_result_file(job_id)
        if data is None:
            # fallback to job summary only
            summary = job.result_json or {}
            return {
                "job_id": job_id,
                "status": job.status,
                "kpi": summary.get("kpi") or {},
                "equity_curve": [],
                "trades_preview": [],
                "download_url": f"/api/v1/research/backtests/{job_id}/download",
                "params": summary.get("params"),
                "codes_loaded": None,
                "codes_requested": (summary.get("params") or {}).get("codes"),
                "codes_missing": None,
            }
        trades = data.get("trades") or []
        codes_loaded = data.get("codes_loaded")
        if isinstance(codes_loaded, int):
            codes_loaded = None
        elif codes_loaded is not None and not isinstance(codes_loaded, list):
            codes_loaded = list(codes_loaded)
        codes_requested = data.get("codes_requested")
        if codes_requested is not None and not isinstance(codes_requested, list):
            codes_requested = list(codes_requested)
        codes_missing = data.get("codes_missing")
        if codes_missing is not None and not isinstance(codes_missing, list):
            codes_missing = list(codes_missing)
        return {
            "job_id": job_id,
            "status": job.status,
            "kpi": data.get("kpi") or {},
            "equity_curve": data.get("equity_curve") or [],
            "trades_preview": trades[:TRADE_PREVIEW_LIMIT],
            "download_url": f"/api/v1/research/backtests/{job_id}/download",
            "params": data.get("params"),
            "codes_loaded": codes_loaded,
            "codes_requested": codes_requested,
            "codes_missing": codes_missing,
        }

    async def download_bytes(
        self,
        session: AsyncSession,
        user: User,
        job_id: int,
    ) -> tuple[bytes, str]:
        job = await self._authorize_job(session, user, job_id)
        if job.status != "success":
            raise ValidationError(
                f"任务未完成: {job.status}",
                details={"code": "BACKTEST_NOT_READY", "status": job.status},
            )
        path = self._runner.result_path(job_id)
        if not path.is_file():
            raise NotFoundError("回测结果文件不存在")
        return path.read_bytes(), path.name

    async def _authorize_job(
        self, session: AsyncSession, user: User, job_id: int
    ) -> PlatformJob:
        job = await self._jobs.get(session, job_id)
        if job.job_type != JOB_TYPE:
            raise NotFoundError("不是回测任务")
        if user.role != "admin" and job.created_by_id != user.id:
            raise ForbiddenError("无权查看该回测任务")
        return job

    async def _assert_no_running(self, session: AsyncSession, user_id: int) -> None:
        await self._reclaim_stale_jobs(session, user_id)
        q = await session.execute(
            select(PlatformJob).where(
                PlatformJob.job_type == JOB_TYPE,
                PlatformJob.created_by_id == user_id,
                PlatformJob.status.in_(("pending", "running")),
            )
        )
        if q.scalars().first() is not None:
            raise ConflictError("已有进行中的回测任务", details={"code": "BACKTEST_BUSY"})

    async def _reclaim_stale_jobs(self, session: AsyncSession, user_id: int) -> None:
        """Mark stuck pending/running jobs failed so a crashed inline worker cannot block forever."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STALE_JOB_MINUTES)
        q = await session.execute(
            select(PlatformJob).where(
                PlatformJob.job_type == JOB_TYPE,
                PlatformJob.created_by_id == user_id,
                PlatformJob.status.in_(("pending", "running")),
                PlatformJob.updated_at < cutoff,
            )
        )
        stale = list(q.scalars().all())
        if not stale:
            return
        for job in stale:
            job.status = "failed"
            job.progress = 100
            job.message = "backtest stale timeout"
            job.error = f"超过 {STALE_JOB_MINUTES} 分钟未完成，已自动释放"
        await session.flush()

    async def _assert_backtest_data(
        self,
        session: AsyncSession,
        start: date,
        end: date,
        *,
        adjust: str = "qfq",
    ) -> None:
        """Lighter than Browser P0: require activated tables + overlap with range.

        Browser readiness also demands coverage back to platform sync_start (often
        2010). Backtests only need bars inside the requested window.
        """
        needed: list[tuple[str, bool]] = [
            ("tushare_stock_basic", False),
            ("tushare_daily", True),
        ]
        if adjust != "none":
            needed.append(("tushare_adj_factor", False))
        errors: list[str] = []
        for data_type, check_range in needed:
            entry = get_data_type_entry(data_type)
            if entry is None or not entry.is_activated or not entry.table_name:
                errors.append(f"{data_type}: 未激活")
                continue
            table = entry.table_name
            try:
                if check_range:
                    row = (
                        await session.execute(
                            text(
                                f'SELECT COUNT(*) FROM "{table}" '
                                f"WHERE trade_date >= :start AND trade_date <= :end"
                            ),
                            {"start": start, "end": end},
                        )
                    ).scalar()
                    if not int(row or 0):
                        errors.append(f"{data_type}: 区间 {start}~{end} 无日线")
                else:
                    row = (await session.execute(text(f'SELECT COUNT(*) FROM "{table}"'))).scalar()
                    if not int(row or 0):
                        errors.append(f"{data_type}: 表无数据")
            except Exception:
                errors.append(f"{data_type}: 表不可读")
        if errors:
            raise ValidationError(
                "数据未就绪，请先补全日线/复权后再回测",
                details={"code": "BACKTEST_NOT_READY", "errors": errors[:8]},
            )

    async def _resolve_codes(
        self, session: AsyncSession, user: User, body: dict[str, Any]
    ) -> list[str]:
        codes: list[str] = []
        watchlist_id = body.get("watchlist_id")
        raw_codes = body.get("codes")
        if watchlist_id is not None:
            wl = await session.get(BrowserWatchlist, int(watchlist_id))
            if wl is None:
                raise NotFoundError("证券池不存在")
            if wl.user_id != user.id and user.role != "admin":
                raise ForbiddenError("无权使用该证券池")
            codes = list(wl.codes_json or [])
        elif raw_codes:
            codes = [str(c).strip().upper() for c in raw_codes if str(c).strip()]
        else:
            raise ValidationError("请提供 watchlist_id 或 codes", details={"code": "BACKTEST_UNIVERSE"})

        cleaned: list[str] = []
        for c in codes:
            c = c.strip().upper()
            if not SYMBOL_RE.match(c):
                raise ValidationError(
                    f"非法代码: {c}（需 ######.SH|SZ）",
                    details={"code": "BACKTEST_SYMBOL"},
                )
            cleaned.append(c)
        # dedupe preserve order
        seen: set[str] = set()
        uniq = []
        for c in cleaned:
            if c not in seen:
                seen.add(c)
                uniq.append(c)
        if not uniq:
            raise ValidationError("证券池为空", details={"code": "BACKTEST_EMPTY"})
        if len(uniq) > MAX_UNIVERSE:
            raise ValidationError(
                f"证券池超过 {MAX_UNIVERSE}",
                details={"code": "BACKTEST_UNIVERSE_LIMIT"},
            )
        return uniq

    @staticmethod
    def _parse_date(value: Any, field: str) -> date:
        if value is None:
            raise ValidationError(f"缺少 {field}", details={"code": "BACKTEST_DATE"})
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError as exc:
            raise ValidationError(f"{field} 格式无效", details={"code": "BACKTEST_DATE"}) from exc
