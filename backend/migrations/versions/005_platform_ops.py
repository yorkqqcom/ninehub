"""005: data_sources, quality_rules/reports, platform_settings."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "005_platform_ops"
down_revision: Union[str, None] = "004_workflow_schedule_job"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("config", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_data_sources_provider", "data_sources", ["provider"])
    op.create_index("ix_data_sources_status", "data_sources", ["status"])

    op.create_table(
        "quality_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("rule_type", sa.String(length=32), nullable=False),
        sa.Column("threshold", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("target_data_type", sa.String(length=64), nullable=False),
        sa.Column("config_json", JSONB(), nullable=True),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quality_rules_target_data_type", "quality_rules", ["target_data_type"])
    op.create_index("ix_quality_rules_is_enabled", "quality_rules", ["is_enabled"])

    op.create_table(
        "quality_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("data_type", sa.String(length=64), nullable=False),
        sa.Column("stock_code", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("detail_json", JSONB(), nullable=True),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["rule_id"], ["quality_rules.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quality_reports_data_type", "quality_reports", ["data_type"])
    op.create_index("ix_quality_reports_status", "quality_reports", ["status"])
    op.create_index("ix_quality_reports_stock_code", "quality_reports", ["stock_code"])

    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("sync_start_date", sa.String(length=10), nullable=False, server_default="2010-01-01"),
        sa.Column("sync_type_overrides", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
    op.drop_index("ix_quality_reports_stock_code", table_name="quality_reports")
    op.drop_index("ix_quality_reports_status", table_name="quality_reports")
    op.drop_index("ix_quality_reports_data_type", table_name="quality_reports")
    op.drop_table("quality_reports")
    op.drop_index("ix_quality_rules_is_enabled", table_name="quality_rules")
    op.drop_index("ix_quality_rules_target_data_type", table_name="quality_rules")
    op.drop_table("quality_rules")
    op.drop_index("ix_data_sources_status", table_name="data_sources")
    op.drop_index("ix_data_sources_provider", table_name="data_sources")
    op.drop_table("data_sources")
