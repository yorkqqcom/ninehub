"""Audit TIA proposals: api_name vs wctapi document/2 page interface name."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tia_proposal import TiaProposal
from app.services.tia.constants import api_to_data_type
from app.services.tia.proposal_enrichment import build_api_meta_map, verify_api_doc_link

AuditStatus = Literal["ok", "doc_mismatch", "no_spec", "no_doc_link"]

# 旧 api 名 → 现网 wctapi 接口名（document/2 页面「接口：」行）
STALE_API_RENAME_MAP: dict[str, str] = {
    "pro": "margin",
    "broker_rec": "cyq_perf",
    "margin_target": "margin_secs",
    "limit_list_d": "limit_cpt_list",
    "barrelated": "dc_daily",
    "st_list": "stock_st",
}
STALE_API_RENAME_HINTS = STALE_API_RENAME_MAP


@dataclass
class ProposalDocLinkRow:
    proposal_id: int | None
    api_name: str
    status: AuditStatus
    doc_id: int | None = None
    doc_url: str | None = None
    page_api: str | None = None
    proposal_status: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProposalDocLinkAuditReport:
    total: int = 0
    ok_count: int = 0
    doc_mismatch_count: int = 0
    no_spec_count: int = 0
    no_doc_link_count: int = 0
    rows: list[ProposalDocLinkRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "ok_count": self.ok_count,
            "doc_mismatch_count": self.doc_mismatch_count,
            "no_spec_count": self.no_spec_count,
            "no_doc_link_count": self.no_doc_link_count,
            "issues": [r.to_dict() for r in self.rows if r.status != "ok"],
            "rows": [r.to_dict() for r in self.rows],
        }


def audit_api_doc_link(
    api_name: str,
    *,
    proposal_id: int | None = None,
    proposal_status: str | None = None,
    candidate_doc_id: int | None = None,
) -> ProposalDocLinkRow:
    """Compare one api_name against wctapi specs (authoritative page api line)."""
    verified = verify_api_doc_link(api_name, candidate_doc_id=candidate_doc_id)
    message = verified.get("message")
    if verified["status"] == "no_spec":
        hint = STALE_API_RENAME_HINTS.get(api_name)
        if hint:
            message = f"{message}；现网可能已更名为 {hint}"
    return ProposalDocLinkRow(
        proposal_id=proposal_id,
        api_name=api_name,
        status=verified["status"],
        doc_id=verified.get("doc_id"),
        doc_url=verified.get("doc_url"),
        page_api=verified.get("page_api"),
        proposal_status=proposal_status,
        message=message,
    )


def audit_proposals(
    proposals: list[TiaProposal | dict[str, Any]],
    *,
    api_meta: dict[str, dict] | None = None,
) -> ProposalDocLinkAuditReport:
    """Audit proposal list: each api_name must match its linked document page."""
    meta = api_meta or build_api_meta_map()
    report = ProposalDocLinkAuditReport()
    seen: set[str] = set()

    for item in proposals:
        if isinstance(item, TiaProposal):
            pid = item.id
            api = item.api_name
            status = item.status
        else:
            pid = item.get("id")
            api = str(item["api_name"])
            status = item.get("status")

        candidate_doc_id = meta.get(api, {}).get("doc_id")
        row = audit_api_doc_link(
            api,
            proposal_id=pid,
            proposal_status=status,
            candidate_doc_id=int(candidate_doc_id) if candidate_doc_id is not None else None,
        )
        report.rows.append(row)
        report.total += 1
        if row.status == "ok":
            report.ok_count += 1
        elif row.status == "doc_mismatch":
            report.doc_mismatch_count += 1
        elif row.status == "no_spec":
            report.no_spec_count += 1
        else:
            report.no_doc_link_count += 1
        seen.add(api)

    return report


@dataclass
class ProposalRenameResult:
    proposal_id: int
    old_api: str
    new_api: str
    action: Literal["renamed", "rejected_duplicate", "skipped"]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def rename_stale_proposal_apis_sync(
    session: Session,
    *,
    rename_map: dict[str, str] | None = None,
    proposal_ids: list[int] | None = None,
) -> list[ProposalRenameResult]:
    """Rename stale proposal api_name to current wctapi names; reject if target exists."""
    mapping = rename_map or STALE_API_RENAME_MAP
    query = select(TiaProposal).where(TiaProposal.api_name.in_(sorted(mapping.keys())))
    if proposal_ids:
        query = query.where(TiaProposal.id.in_(proposal_ids))
    proposals = list(session.execute(query).scalars().all())

    existing_apis = set(session.execute(select(TiaProposal.api_name)).scalars().all())
    results: list[ProposalRenameResult] = []

    for proposal in proposals:
        old_api = proposal.api_name
        new_api = mapping.get(old_api)
        if not new_api:
            continue

        if new_api in existing_apis and new_api != old_api:
            proposal.status = "rejected"
            proposal.reason = f"api_renamed_duplicate:{new_api}"
            proposal.reviewer_note = (
                f"旧名 {old_api} 对应现网 {new_api}，但提案库已存在 {new_api}，自动拒绝重复项"
            )
            results.append(
                ProposalRenameResult(
                    proposal_id=int(proposal.id),
                    old_api=old_api,
                    new_api=new_api,
                    action="rejected_duplicate",
                    message=proposal.reviewer_note,
                )
            )
            continue

        verified = verify_api_doc_link(new_api)
        if verified["status"] != "ok":
            results.append(
                ProposalRenameResult(
                    proposal_id=int(proposal.id),
                    old_api=old_api,
                    new_api=new_api,
                    action="skipped",
                    message=f"目标接口 {new_api} 无 wctapi 文档页，未改名",
                )
            )
            continue

        proposal.api_name = new_api
        proposal.data_type = api_to_data_type(new_api)
        proposal.reason = f"api_renamed_from:{old_api}"
        existing_apis.discard(old_api)
        existing_apis.add(new_api)
        results.append(
            ProposalRenameResult(
                proposal_id=int(proposal.id),
                old_api=old_api,
                new_api=new_api,
                action="renamed",
                message=f"{old_api} → {new_api}",
            )
        )

    session.flush()
    return results
