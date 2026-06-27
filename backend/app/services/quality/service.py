"""Quality rule engine and report generation."""

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.catalog.registry import get_data_type_entry
from app.core.exceptions import NotFoundError, ValidationError
from app.models.quality import QualityReport, QualityRule
from app.schemas.quality import (
    QualityReportPageResponse,
    QualityReportResponse,
    QualityRuleCreate,
    QualityRulePageResponse,
    QualityRuleResponse,
    QualityRuleUpdate,
    QualityRunResponse,
)
from app.services.catalog_query import CatalogQueryService
from app.services.quality.alert_service import QualityAlertService


def resolve_no_null_fields(rule: QualityRule) -> list[str]:
    """Resolve columns to check: fields (preferred), legacy column, or all catalog columns."""
    cfg = rule.config_json or {}
    fields = cfg.get("fields")
    if fields:
        return list(fields) if isinstance(fields, list) else [str(fields)]
    column = cfg.get("column")
    if column:
        return [column] if isinstance(column, str) else [str(c) for c in column]
    entry = get_data_type_entry(rule.target_data_type)
    return [c.key for c in entry.columns] if entry else []


class QualityService:
    def __init__(self) -> None:
        self._query = CatalogQueryService()
        self._alerts = QualityAlertService()

    def _rule_response(self, rule: QualityRule) -> QualityRuleResponse:
        return QualityRuleResponse.model_validate(rule)

    def _report_response(self, report: QualityReport) -> QualityReportResponse:
        return QualityReportResponse.model_validate(report)

    def _validate_data_type(self, data_type: str) -> None:
        if get_data_type_entry(data_type) is None:
            raise ValidationError(
                f"Unknown data_type '{data_type}'",
                details={"data_type": data_type},
            )

    async def list_rules(
        self,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        target_data_type: str | None = None,
    ) -> QualityRulePageResponse:
        query = select(QualityRule)
        count_q = select(func.count()).select_from(QualityRule)
        if target_data_type:
            query = query.where(QualityRule.target_data_type == target_data_type)
            count_q = count_q.where(QualityRule.target_data_type == target_data_type)
        total = (await session.execute(count_q)).scalar_one()
        result = await session.execute(
            query.order_by(QualityRule.id.desc()).offset(skip).limit(limit)
        )
        page = (skip // limit) + 1 if limit else 1
        return QualityRulePageResponse(
            items=[self._rule_response(r) for r in result.scalars().all()],
            total=total,
            page=page,
            size=limit,
        )

    async def create_rule(
        self, session: AsyncSession, body: QualityRuleCreate
    ) -> QualityRuleResponse:
        self._validate_data_type(body.target_data_type)
        rule = QualityRule(
            name=body.name,
            rule_type=body.rule_type,
            threshold=body.threshold,
            target_data_type=body.target_data_type,
            config_json=body.config_json,
            is_enabled=body.is_enabled,
        )
        session.add(rule)
        await session.flush()
        await session.refresh(rule)
        return self._rule_response(rule)

    async def update_rule(
        self, session: AsyncSession, rule_id: int, body: QualityRuleUpdate
    ) -> QualityRuleResponse:
        rule = await session.get(QualityRule, rule_id)
        if rule is None:
            raise NotFoundError(f"Quality rule {rule_id} not found")
        if body.target_data_type is not None:
            self._validate_data_type(body.target_data_type)
            rule.target_data_type = body.target_data_type
        if body.name is not None:
            rule.name = body.name
        if body.rule_type is not None:
            rule.rule_type = body.rule_type
        if body.threshold is not None:
            rule.threshold = body.threshold
        if body.config_json is not None:
            rule.config_json = body.config_json
        if body.is_enabled is not None:
            rule.is_enabled = body.is_enabled
        await session.flush()
        await session.refresh(rule)
        return self._rule_response(rule)

    async def list_reports(
        self,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        data_type: str | None = None,
        stock_code: str | None = None,
        status: str | None = None,
    ) -> QualityReportPageResponse:
        query = select(QualityReport)
        count_q = select(func.count()).select_from(QualityReport)
        if data_type:
            query = query.where(QualityReport.data_type == data_type)
            count_q = count_q.where(QualityReport.data_type == data_type)
        if stock_code:
            query = query.where(QualityReport.stock_code == stock_code)
            count_q = count_q.where(QualityReport.stock_code == stock_code)
        if status:
            query = query.where(QualityReport.status == status)
            count_q = count_q.where(QualityReport.status == status)
        total = (await session.execute(count_q)).scalar_one()
        result = await session.execute(
            query.order_by(QualityReport.id.desc()).offset(skip).limit(limit)
        )
        page = (skip // limit) + 1 if limit else 1
        return QualityReportPageResponse(
            items=[self._report_response(r) for r in result.scalars().all()],
            total=total,
            page=page,
            size=limit,
        )

    async def run_check(
        self,
        session: AsyncSession,
        data_type: str | None = None,
        stock_code: str | None = None,
    ) -> QualityRunResponse:
        reports = await self._execute_all_rules(session, data_type, stock_code)
        await session.flush()
        alerts_sent = self._alerts.notify_failed_reports(reports)
        return QualityRunResponse(
            reports_created=len(reports),
            message=f"已生成 {len(reports)} 条质检报告",
            alerts_sent=alerts_sent,
        )

    def run_check_sync(
        self,
        session: Session,
        data_type: str | None = None,
        stock_code: str | None = None,
    ) -> QualityRunResponse:
        reports = self._execute_all_rules_sync(session, data_type, stock_code)
        session.flush()
        alerts_sent = self._alerts.notify_failed_reports(reports)
        return QualityRunResponse(
            reports_created=len(reports),
            message=f"已生成 {len(reports)} 条质检报告",
            alerts_sent=alerts_sent,
        )

    async def _execute_all_rules(
        self,
        session: AsyncSession,
        data_type: str | None,
        stock_code: str | None,
    ) -> list[QualityReport]:
        query = select(QualityRule).where(QualityRule.is_enabled.is_(True))
        if data_type:
            query = query.where(QualityRule.target_data_type == data_type)
        result = await session.execute(query)
        rules = result.scalars().all()
        if not rules:
            return []
        reports: list[QualityReport] = []
        for rule in rules:
            report = await self._execute_rule(session, rule, stock_code)
            if report:
                session.add(report)
                reports.append(report)
        return reports

    def _execute_all_rules_sync(
        self,
        session: Session,
        data_type: str | None,
        stock_code: str | None,
    ) -> list[QualityReport]:
        query = select(QualityRule).where(QualityRule.is_enabled.is_(True))
        if data_type:
            query = query.where(QualityRule.target_data_type == data_type)
        rules = session.execute(query).scalars().all()
        if not rules:
            return []
        reports: list[QualityReport] = []
        for rule in rules:
            report = self._execute_rule_sync(session, rule, stock_code)
            if report:
                session.add(report)
                reports.append(report)
        return reports

    async def _execute_rule(
        self,
        session: AsyncSession,
        rule: QualityRule,
        stock_code: str | None,
    ) -> QualityReport | None:
        if rule.rule_type == "min_rows":
            return await self._check_min_rows(session, rule, stock_code)
        if rule.rule_type == "no_nulls":
            return await self._check_no_nulls(session, rule, stock_code)
        if rule.rule_type == "cross_table_count":
            return await self._check_cross_table_count(session, rule)
        return QualityReport(
            data_type=rule.target_data_type,
            stock_code=stock_code,
            status="failed",
            rule_id=rule.id,
            detail_json={"error": f"Unknown rule_type: {rule.rule_type}"},
        )

    def _execute_rule_sync(
        self,
        session: Session,
        rule: QualityRule,
        stock_code: str | None,
    ) -> QualityReport | None:
        if rule.rule_type == "min_rows":
            return self._check_min_rows_sync(session, rule, stock_code)
        if rule.rule_type == "no_nulls":
            return self._check_no_nulls_sync(session, rule, stock_code)
        if rule.rule_type == "cross_table_count":
            return self._check_cross_table_count_sync(session, rule)
        return QualityReport(
            data_type=rule.target_data_type,
            stock_code=stock_code,
            status="failed",
            rule_id=rule.id,
            detail_json={"error": f"Unknown rule_type: {rule.rule_type}"},
        )

    async def _check_min_rows(
        self,
        session: AsyncSession,
        rule: QualityRule,
        stock_code: str | None,
    ) -> QualityReport:
        min_rows = int(rule.threshold or 1)
        filters = {"stock_code": stock_code} if stock_code else {}
        row_count = await self._query.count_rows(session, rule.target_data_type, filters)
        passed = row_count >= min_rows
        return QualityReport(
            data_type=rule.target_data_type,
            stock_code=stock_code,
            status="passed" if passed else "failed",
            rule_id=rule.id,
            detail_json={
                "rule_type": "min_rows",
                "row_count": row_count,
                "threshold": min_rows,
            },
        )

    def _check_min_rows_sync(
        self,
        session: Session,
        rule: QualityRule,
        stock_code: str | None,
    ) -> QualityReport:
        min_rows = int(rule.threshold or 1)
        filters = {"stock_code": stock_code} if stock_code else {}
        row_count = self._query.count_rows_sync(session, rule.target_data_type, filters)
        passed = row_count >= min_rows
        return QualityReport(
            data_type=rule.target_data_type,
            stock_code=stock_code,
            status="passed" if passed else "failed",
            rule_id=rule.id,
            detail_json={
                "rule_type": "min_rows",
                "row_count": row_count,
                "threshold": min_rows,
            },
        )

    async def _check_no_nulls(
        self,
        session: AsyncSession,
        rule: QualityRule,
        stock_code: str | None,
    ) -> QualityReport:
        fields = resolve_no_null_fields(rule)
        null_counts = await self._null_counts_generic(
            session, rule.target_data_type, fields, stock_code
        )
        total_nulls = sum(null_counts.values())
        return QualityReport(
            data_type=rule.target_data_type,
            stock_code=stock_code,
            status="passed" if total_nulls == 0 else "failed",
            rule_id=rule.id,
            detail_json={"rule_type": "no_nulls", "null_counts": null_counts},
        )

    def _check_no_nulls_sync(
        self,
        session: Session,
        rule: QualityRule,
        stock_code: str | None,
    ) -> QualityReport:
        fields = resolve_no_null_fields(rule)
        null_counts = self._null_counts_generic_sync(
            session, rule.target_data_type, fields, stock_code
        )
        total_nulls = sum(null_counts.values())
        return QualityReport(
            data_type=rule.target_data_type,
            stock_code=stock_code,
            status="passed" if total_nulls == 0 else "failed",
            rule_id=rule.id,
            detail_json={"rule_type": "no_nulls", "null_counts": null_counts},
        )

    async def _null_counts_generic(
        self,
        session: AsyncSession,
        data_type: str,
        fields: list[str],
        stock_code: str | None,
    ) -> dict[str, Any]:
        filters = {"stock_code": stock_code} if stock_code else {}
        return await self._query.count_nulls(session, data_type, fields, filters)

    def _null_counts_generic_sync(
        self,
        session: Session,
        data_type: str,
        fields: list[str],
        stock_code: str | None,
    ) -> dict[str, Any]:
        filters = {"stock_code": stock_code} if stock_code else {}
        return self._query.count_nulls_sync(session, data_type, fields, filters)

    async def _check_cross_table_count(
        self,
        session: AsyncSession,
        rule: QualityRule,
    ) -> QualityReport:
        return self._check_cross_table_count_sync(session, rule)

    def _check_cross_table_count_sync(
        self,
        session: Session,
        rule: QualityRule,
    ) -> QualityReport:
        cfg = rule.config_json or {}
        ref_type = str(cfg.get("reference_data_type") or "")
        threshold = float(rule.threshold or 0.8)
        target_count = self._query.count_rows_sync(session, rule.target_data_type, {})
        ref_count = self._query.count_rows_sync(session, ref_type, {}) if ref_type else 0
        if ref_count <= 0:
            return QualityReport(
                data_type=rule.target_data_type,
                stock_code=None,
                status="passed",
                rule_id=rule.id,
                detail_json={
                    "rule_type": "cross_table_count",
                    "skipped": True,
                    "reason": f"reference {ref_type} empty or missing",
                    "target_count": target_count,
                },
            )
        ratio = target_count / ref_count if ref_count else 0.0
        passed = ratio >= threshold
        return QualityReport(
            data_type=rule.target_data_type,
            stock_code=None,
            status="passed" if passed else "failed",
            rule_id=rule.id,
            detail_json={
                "rule_type": "cross_table_count",
                "target_count": target_count,
                "reference_count": ref_count,
                "ratio": round(ratio, 4),
                "threshold": threshold,
                "reference_data_type": ref_type,
            },
        )
