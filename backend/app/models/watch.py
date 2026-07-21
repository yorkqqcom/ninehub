"""Watch (盯盘) persistence models."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class WatchProfile(Base, TimestampMixin):
    __tablename__ = "watch_profiles"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watch_profiles_user_id_name"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128), default="default")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    config_revision: Mapped[int] = mapped_column(Integer, default=0)
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
    )


class WatchAlertEvent(Base, TimestampMixin):
    __tablename__ = "watch_alert_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("watch_profiles.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str] = mapped_column(String(16), default="")
    rule_id: Mapped[str] = mapped_column(String(64), default="")
    event_type: Mapped[str] = mapped_column(String(32), default="quote_alert", index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
    )


class WatchCooldownState(Base, TimestampMixin):
    __tablename__ = "watch_cooldown_state"
    __table_args__ = (UniqueConstraint("profile_id", name="uq_watch_cooldown_state_profile_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("watch_profiles.id", ondelete="CASCADE"), index=True
    )
    state_json: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
    )


class WatchEngineGate(Base, TimestampMixin):
    """Singleton row (id=1) used as FOR UPDATE lock anchor for enabled-profile caps."""

    __tablename__ = "watch_engine_gate"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
