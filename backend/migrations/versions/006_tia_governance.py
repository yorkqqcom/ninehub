"""006: tia_overrides and proposal review fields."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "006_tia_governance"
down_revision: Union[str, None] = "005_platform_ops"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tia_overrides",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("api_name", sa.String(length=64), nullable=False),
        sa.Column("data_type", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False, server_default="financial"),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("min_points", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("doc_url", sa.String(length=255), nullable=True),
        sa.Column("table_name", sa.String(length=64), nullable=True),
        sa.Column("is_activated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("override_json", JSONB(), nullable=True),
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
        sa.UniqueConstraint("api_name"),
        sa.UniqueConstraint("data_type"),
    )
    op.create_index("ix_tia_overrides_data_type", "tia_overrides", ["data_type"])

    op.add_column("tia_proposals", sa.Column("data_type", sa.String(length=64), nullable=True))
    op.add_column("tia_proposals", sa.Column("reviewer_note", sa.Text(), nullable=True))
    op.add_column("tia_proposals", sa.Column("approved_by_id", sa.Integer(), nullable=True))
    op.add_column("tia_proposals", sa.Column("activation_steps", JSONB(), nullable=True))
    op.create_foreign_key(
        "fk_tia_proposals_approved_by",
        "tia_proposals",
        "users",
        ["approved_by_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_tia_proposals_approved_by", "tia_proposals", type_="foreignkey")
    op.drop_column("tia_proposals", "activation_steps")
    op.drop_column("tia_proposals", "approved_by_id")
    op.drop_column("tia_proposals", "reviewer_note")
    op.drop_column("tia_proposals", "data_type")
    op.drop_index("ix_tia_overrides_data_type", table_name="tia_overrides")
    op.drop_table("tia_overrides")
