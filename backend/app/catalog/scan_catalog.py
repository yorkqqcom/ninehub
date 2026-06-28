"""Merged local catalog view for TIA scan (L1 overrides / L3 applied proposals)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tia_override import TiaOverride
from app.models.tia_proposal import TiaProposal


def local_api_names(session: Session | None = None) -> set[str]:
    """Runtime local catalog = tia_overrides.api_name only."""
    if session is None:
        return set()
    rows = session.execute(select(TiaOverride.api_name)).scalars().all()
    return set(rows)


def local_api_names_sorted(session: Session | None = None) -> list[str]:
    return sorted(local_api_names(session))


def local_provider_api_names(session: Session | None, provider: str) -> set[str]:
    """Provider-specific local catalog for scan diff."""
    if session is None:
        return set()
    if provider == "tushare":
        return local_api_names(session)
    if provider == "tdx":
        rows = session.execute(
            select(TiaProposal.api_name).where(
                TiaProposal.status == "applied",
                TiaProposal.data_type.ilike("tdx_%"),
            )
        ).scalars().all()
        return set(rows)
    return set()


def local_provider_api_names_sorted(session: Session | None, provider: str) -> list[str]:
    return sorted(local_provider_api_names(session, provider))


def local_override_min_points(session: Session | None = None) -> dict[str, int]:
    """L1 override min_points keyed by api_name (empty when no session)."""
    if session is None:
        return {}
    rows = session.execute(select(TiaOverride.api_name, TiaOverride.min_points)).all()
    return {row[0]: int(row[1]) for row in rows}
