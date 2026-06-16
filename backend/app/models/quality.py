"""Quality rule and report models."""

from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import JSON, Boolean, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class QualityRule(Base, TimestampMixin):
    __tablename__ = "quality_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    rule_type: Mapped[str] = mapped_column(String(32))
    threshold: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 4), nullable=True)
    target_data_type: Mapped[str] = mapped_column(String(64), index=True)
    config_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class QualityReport(Base, TimestampMixin):
    __tablename__ = "quality_reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    data_type: Mapped[str] = mapped_column(String(64), index=True)
    stock_code: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    detail_json: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),
        nullable=True,
    )
    rule_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quality_rules.id"), nullable=True)
