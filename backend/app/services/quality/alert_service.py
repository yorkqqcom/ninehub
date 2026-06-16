"""Quality check failure alerting (G-06)."""

import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class QualityAlertService:
    def notify_failed_reports(self, reports: list[Any]) -> int:
        failed = [r for r in reports if getattr(r, "status", None) == "failed"]
        if not failed:
            return 0
        for report in failed:
            logger.warning(
                "quality_check_failed data_type=%s stock_code=%s rule_id=%s detail=%s",
                report.data_type,
                report.stock_code,
                report.rule_id,
                report.detail_json,
            )
        settings = get_settings()
        if settings.quality_alert_webhook_url:
            self._post_webhook(settings.quality_alert_webhook_url, failed)
        return len(failed)

    def _post_webhook(self, url: str, reports: list[Any]) -> None:
        payload = {
            "event": "quality_check_failed",
            "count": len(reports),
            "reports": [
                {
                    "data_type": r.data_type,
                    "stock_code": r.stock_code,
                    "rule_id": r.rule_id,
                    "detail_json": r.detail_json,
                }
                for r in reports
            ],
        }
        try:
            httpx.post(url, json=payload, timeout=10.0)
        except Exception as exc:
            logger.error("quality_alert_webhook_failed: %s", exc)
