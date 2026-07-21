"""Orchestrate backtest job: load bars → simulate → write export file."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ValidationError
from app.services.platform.job_service import PlatformJobService
from app.services.research.bar_loader import BarLoader
from app.services.research.broker import run_backtest
from app.services.research.constants import TRADE_PREVIEW_LIMIT
from app.services.research.signals import SIGNAL_REGISTRY, normalize_signal_params

logger = logging.getLogger(__name__)


class BacktestRunner:
    def __init__(self) -> None:
        self._jobs = PlatformJobService()
        self._loader = BarLoader()

    def export_dir(self) -> Path:
        settings = get_settings()
        path = Path(settings.static_dir) / settings.export_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    def result_path(self, job_id: int) -> Path:
        return self.export_dir() / f"backtest_{job_id}.json"

    def write_result_file(self, job_id: int, body: dict[str, Any]) -> Path:
        path = self.result_path(job_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return path

    async def run_job(self, session: AsyncSession, job_id: int) -> dict[str, Any]:
        job = await self._jobs.get(session, job_id)
        if job.status == "success" and self.result_path(job_id).is_file():
            data = self.read_result_file(job_id) or {}
            return {"job_id": job_id, "status": "success", "kpi": data.get("kpi") or {}}
        payload = (job.result_json or {}).get("params") or {}
        if not payload.get("start_date") or not payload.get("end_date"):
            raise ValidationError("任务缺少日期参数", details={"code": "BACKTEST_PARAMS"})
        codes: list[str] = list(payload.get("codes") or [])
        if not codes:
            raise ValidationError("任务证券池为空", details={"code": "BACKTEST_EMPTY"})
        signal_id = str(payload.get("signal_id") or "")
        if signal_id not in SIGNAL_REGISTRY:
            raise ValidationError(f"未知信号: {signal_id}", details={"code": "BACKTEST_SIGNAL"})
        try:
            params = normalize_signal_params(signal_id, dict(payload.get("params") or {}))
        except KeyError as exc:
            raise ValidationError(f"未知信号: {signal_id}", details={"code": "BACKTEST_SIGNAL"}) from exc
        adjust = str(payload.get("adjust") or "qfq")
        commission_bps = float(payload.get("commission_bps") or 5)
        slippage_bps = float(payload.get("slippage_bps") or 5)
        max_positions = int(payload.get("max_positions") or 5)
        try:
            start = date.fromisoformat(str(payload["start_date"])[:10])
            end = date.fromisoformat(str(payload["end_date"])[:10])
        except ValueError as exc:
            raise ValidationError("任务日期无效", details={"code": "BACKTEST_DATE"}) from exc

        await self._jobs.update(
            session, job_id, status="running", progress=15, message="loading bars"
        )
        await session.commit()

        bars = await self._loader.load(session, codes, start, end, adjust=adjust)
        await self._jobs.update(session, job_id, progress=55, message="simulating")
        await session.commit()

        if not bars:
            raise ValidationError(
                "区间内无日线数据",
                details={"code": "BACKTEST_NO_BARS"},
            )

        result = run_backtest(
            bars,
            signal_id=signal_id,
            params=params,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            max_positions=max_positions,
        )

        missing = sorted(set(codes) - set(bars.keys()))
        body = {
            "job_id": job_id,
            "params": {**payload, "params": params},
            "kpi": result.kpi,
            "equity_curve": result.equity_curve,
            "trades": result.trades,
            "codes_loaded": sorted(bars.keys()),
            "codes_requested": codes,
            "codes_missing": missing,
        }
        path = self.write_result_file(job_id, body)

        summary = {
            "params": body["params"],
            "kpi": result.kpi,
            "download_path": str(path.name),
            "summary_ref": f"backtest_{job_id}.json",
            "codes_loaded": len(bars),
            "codes_missing": len(missing),
            "trade_preview_limit": TRADE_PREVIEW_LIMIT,
        }
        await self._jobs.update(
            session,
            job_id,
            status="success",
            progress=100,
            message="backtest completed",
            result_json=summary,
            error=None,
        )
        await session.commit()
        return {"job_id": job_id, "status": "success", "kpi": result.kpi}

    def read_result_file(self, job_id: int) -> dict[str, Any] | None:
        path = self.result_path(job_id)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning("corrupt backtest result %s: %s", path, exc)
            return None
