"""TIA proposal service."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal
from app.schemas.tia_proposal import (
    TiaProposalMinPointsUpdate,
    TiaProposalPageResponse,
    TiaProposalResponse,
    TiaProposalReview,
    TiaProposalSummary,
)
from app.services.tia.constants import api_to_data_type
from app.services.tia.override_service import TiaOverrideService
from app.services.tia.proposal_enrichment import (
    apis_matching_points_filter,
    build_api_meta_map,
    enrich_proposal,
    resolve_doc_min_points,
)

_VALID_STATUSES = frozenset({"pending", "approved", "rejected", "applied", "failed"})
_EDITABLE_MIN_POINTS_STATUSES = frozenset({"pending", "approved", "applied", "failed"})


class TiaProposalService:
    def __init__(self) -> None:
        self._overrides = TiaOverrideService()

    def reconcile_local_catalog_proposals_sync(
        self,
        session: Session,
        local_apis: list[str],
    ) -> int:
        """Reject stale pending proposals for APIs already in local catalog."""
        if not local_apis:
            return 0
        rows = (
            session.execute(
                select(TiaProposal).where(
                    TiaProposal.status == "pending",
                    TiaProposal.api_name.in_(local_apis),
                )
            )
            .scalars()
            .all()
        )
        for proposal in rows:
            proposal.status = "rejected"
            proposal.reason = "already_in_local_catalog"
            proposal.reviewer_note = "auto: already in local catalog"
        session.flush()
        return len(rows)

    def count_pending_sync(self, session: Session) -> int:
        return int(
            session.execute(
                select(func.count())
                .select_from(TiaProposal)
                .where(TiaProposal.status == "pending")
            ).scalar_one()
        )

    def upsert_from_scan_sync(
        self,
        session: Session,
        job_id: int,
        new_apis: list[str],
    ) -> int:
        created = 0
        for api in new_apis:
            existing = session.execute(
                select(TiaProposal).where(
                    TiaProposal.api_name == api,
                    TiaProposal.status == "pending",
                )
            ).scalar_one_or_none()
            if existing:
                existing.job_id = job_id
                existing.reason = "new_on_official"
                continue
            session.add(
                TiaProposal(
                    api_name=api,
                    status="pending",
                    action="review",
                    reason="new_on_official",
                    job_id=job_id,
                    data_type=api_to_data_type(api),
                )
            )
            created += 1
        session.flush()
        return created

    async def get_proposal(self, session: AsyncSession, proposal_id: int) -> TiaProposal:
        proposal = await session.get(TiaProposal, proposal_id)
        if proposal is None:
            raise NotFoundError(f"Proposal {proposal_id} not found")
        return proposal

    async def get_proposal_response(
        self, session: AsyncSession, proposal_id: int
    ) -> TiaProposalResponse:
        proposal = await self.get_proposal(session, proposal_id)
        api_meta = build_api_meta_map()
        override_rows = (
            await session.execute(select(TiaOverride.api_name, TiaOverride.min_points))
        ).all()
        override_points = {row[0]: int(row[1]) for row in override_rows}
        return self._to_response(proposal, api_meta, override_points, include_spec=True)

    @staticmethod
    def _apply_filters(
        query,
        *,
        status: str | None,
        q: str | None,
        api_names: set[str] | None = None,
    ):
        if status:
            query = query.where(TiaProposal.status == status)
        if q:
            like = f"%{q.strip()}%"
            query = query.where(
                or_(
                    TiaProposal.api_name.ilike(like),
                    TiaProposal.data_type.ilike(like),
                    TiaProposal.reason.ilike(like),
                )
            )
        if api_names is not None:
            if not api_names:
                query = query.where(TiaProposal.id < 0)
            else:
                query = query.where(TiaProposal.api_name.in_(api_names))
        return query

    async def status_summary(self, session: AsyncSession) -> TiaProposalSummary:
        rows = (
            await session.execute(
                select(TiaProposal.status, func.count()).group_by(TiaProposal.status)
            )
        ).all()
        counts = {status: int(cnt) for status, cnt in rows}
        summary = TiaProposalSummary(
            pending=counts.get("pending", 0),
            approved=counts.get("approved", 0),
            rejected=counts.get("rejected", 0),
            applied=counts.get("applied", 0),
            failed=counts.get("failed", 0),
        )
        summary.total = (
            summary.pending
            + summary.approved
            + summary.rejected
            + summary.applied
            + summary.failed
        )
        return summary

    @staticmethod
    def _to_response(
        proposal: TiaProposal,
        api_meta: dict[str, dict] | None = None,
        override_points: dict[str, int] | None = None,
        *,
        include_spec: bool = False,
    ) -> TiaProposalResponse:
        base = TiaProposalResponse.model_validate(proposal)
        extra = enrich_proposal(
            proposal, api_meta, override_points, include_spec=include_spec
        )
        return base.model_copy(update=extra)

    async def list_proposals(
        self,
        session: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        status: str | None = None,
        q: str | None = None,
        min_points_gte: int | None = None,
        min_points_lte: int | None = None,
        include_summary: bool = True,
    ) -> TiaProposalPageResponse:
        if status and status not in _VALID_STATUSES:
            raise ValidationError(f"Invalid status filter: {status}")
        if min_points_gte is not None and min_points_gte < 0:
            raise ValidationError("min_points_gte must be >= 0")
        if min_points_lte is not None and min_points_lte < 0:
            raise ValidationError("min_points_lte must be >= 0")
        if (
            min_points_gte is not None
            and min_points_lte is not None
            and min_points_gte > min_points_lte
        ):
            raise ValidationError("min_points_gte cannot exceed min_points_lte")

        api_meta = build_api_meta_map()
        override_rows = (
            await session.execute(select(TiaOverride.api_name, TiaOverride.min_points))
        ).all()
        override_points = {row[0]: int(row[1]) for row in override_rows}

        proposal_override_points: dict[str, int] = {}
        if min_points_gte is not None or min_points_lte is not None:
            prop_override_rows = (
                await session.execute(
                    select(TiaProposal.api_name, TiaProposal.min_points_override).where(
                        TiaProposal.min_points_override.isnot(None)
                    )
                )
            ).all()
            proposal_override_points = {row[0]: int(row[1]) for row in prop_override_rows}

        points_apis: set[str] | None = None
        if min_points_gte is not None or min_points_lte is not None:
            scope_q = select(TiaProposal.api_name).distinct()
            scope_q = self._apply_filters(scope_q, status=status, q=q, api_names=None)
            api_names_in_scope = set((await session.execute(scope_q)).scalars().all())
            points_apis = apis_matching_points_filter(
                api_names_in_scope,
                min_points_gte=min_points_gte,
                min_points_lte=min_points_lte,
                api_meta=api_meta,
                override_points=override_points,
                proposal_override_points=proposal_override_points,
            )

        query = select(TiaProposal)
        query = self._apply_filters(
            query, status=status, q=q, api_names=points_apis
        )

        count_q = select(func.count()).select_from(TiaProposal)
        count_q = self._apply_filters(
            count_q, status=status, q=q, api_names=points_apis
        )
        total = (await session.execute(count_q)).scalar_one()

        result = await session.execute(
            query.order_by(TiaProposal.id.desc()).offset(skip).limit(limit)
        )
        items_raw = result.scalars().all()
        items = [
            self._to_response(p, api_meta, override_points, include_spec=False)
            for p in items_raw
        ]
        page = (skip // limit) + 1 if limit else 1
        summary = await self.status_summary(session) if include_summary else None
        return TiaProposalPageResponse(
            items=items,
            total=total,
            page=page,
            size=limit,
            summary=summary,
        )

    async def review_proposal(
        self,
        session: AsyncSession,
        proposal_id: int,
        body: TiaProposalReview,
        approved_by_id: int,
    ) -> TiaProposalResponse:
        proposal = await self.get_proposal(session, proposal_id)
        if proposal.status != "pending":
            raise ValidationError(f"Cannot review proposal in status {proposal.status}")
        proposal.reviewer_note = body.note
        proposal.approved_by_id = approved_by_id
        if body.status == "rejected":
            proposal.status = "rejected"
            await session.flush()
            return self._to_response(proposal)
        proposal.status = "approved"
        proposal.data_type = api_to_data_type(proposal.api_name)
        existing = await session.execute(
            select(TiaOverride).where(TiaOverride.api_name == proposal.api_name)
        )
        if existing.scalar_one_or_none() is None:
            await self._overrides.create_from_api(
                session,
                proposal.api_name,
                domain=body.domain,
                min_points=proposal.min_points_override,
            )
        await session.flush()
        await session.refresh(proposal)

        if body.status == "approved" and body.run_preflight:
            from app.services.tia.preflight_test_service import TiaPreflightTestService

            result = await session.run_sync(
                lambda sync_sess: TiaPreflightTestService().run(
                    sync_sess, proposal.api_name, live_probe=True
                )
            )
            steps = dict(proposal.activation_steps or {})
            steps["preflight_test"] = result.to_activation_step()
            proposal.activation_steps = steps
            if not result.passed:
                raise ValidationError(
                    "Preflight 测试未通过: "
                    + "; ".join(result.blocking_errors or ["存在失败项"])
                )
            await session.flush()
            await session.refresh(proposal)

        return self._to_response(proposal)

    async def update_min_points(
        self,
        session: AsyncSession,
        proposal_id: int,
        body: TiaProposalMinPointsUpdate,
    ) -> TiaProposalResponse:
        proposal = await self.get_proposal(session, proposal_id)
        if proposal.status not in _EDITABLE_MIN_POINTS_STATUSES:
            raise ValidationError(
                f"Cannot edit min_points for proposal in status {proposal.status}"
            )

        api_meta = build_api_meta_map()

        proposal.min_points_override = body.min_points

        existing = await session.execute(
            select(TiaOverride).where(TiaOverride.api_name == proposal.api_name)
        )
        l1_override = existing.scalar_one_or_none()
        if l1_override is not None:
            if body.min_points is not None:
                l1_override.min_points = int(body.min_points)
            else:
                doc_pts = resolve_doc_min_points(proposal.api_name, api_meta)
                if doc_pts is not None:
                    l1_override.min_points = int(doc_pts)

        await session.flush()
        await session.refresh(proposal)
        override_rows = (
            await session.execute(select(TiaOverride.api_name, TiaOverride.min_points))
        ).all()
        override_points = {row[0]: int(row[1]) for row in override_rows}
        return self._to_response(proposal, api_meta, override_points, include_spec=False)

    async def batch_review_proposals(
        self,
        session: AsyncSession,
        proposal_ids: list[int],
        body: TiaProposalReview,
        approved_by_id: int,
        *,
        auto_activate: bool = False,
    ) -> tuple[list[TiaProposalResponse], list[int]]:
        results: list[TiaProposalResponse] = []
        activate_ids: list[int] = []
        for pid in proposal_ids:
            review = TiaProposalReview(
                status=body.status,
                note=body.note,
                domain=body.domain,
            )
            resp = await self.review_proposal(session, pid, review, approved_by_id)
            results.append(resp)
            if auto_activate and body.status == "approved":
                activate_ids.append(pid)
        return results, activate_ids

    async def approve_and_get_id(
        self,
        session: AsyncSession,
        proposal_id: int,
        approved_by_id: int,
        note: str | None = None,
        domain: str | None = None,
    ) -> TiaProposalResponse:
        review = TiaProposalReview(status="approved", note=note, domain=domain)
        return await self.review_proposal(session, proposal_id, review, approved_by_id)

    async def batch_enable_browse(
        self,
        session: AsyncSession,
        proposal_ids: list[int],
    ) -> tuple[list[TiaProposalResponse], list[dict[str, str | int]]]:
        results: list[TiaProposalResponse] = []
        errors: list[dict[str, str | int]] = []
        api_meta = build_api_meta_map()
        override_rows = (
            await session.execute(select(TiaOverride.api_name, TiaOverride.min_points))
        ).all()
        override_points = {row[0]: int(row[1]) for row in override_rows}
        for pid in proposal_ids:
            try:
                proposal = await self.get_proposal(session, pid)
                if proposal.status != "applied":
                    errors.append(
                        {
                            "proposal_id": pid,
                            "error": f"Proposal must be applied, got {proposal.status}",
                        }
                    )
                    continue
                await self._overrides.enable_browse(session, proposal.api_name)
                await session.flush()
                results.append(self._to_response(proposal, api_meta, override_points))
            except (NotFoundError, ValidationError) as exc:
                errors.append({"proposal_id": pid, "error": exc.message})
        return results, errors
