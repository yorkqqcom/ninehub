"""007: drop legacy stock_daily table (builtin daily_ohlcv removed)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007_drop_stock_daily"
down_revision: Union[str, None] = "006_tia_governance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_stock_daily_trade_date", table_name="stock_daily")
    op.drop_index("ix_stock_daily_stock_code", table_name="stock_daily")
    op.drop_table("stock_daily")


def downgrade() -> None:
    op.create_table(
        "stock_daily",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stock_code", sa.String(length=16), nullable=False),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("high", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("low", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("close", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("vol", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stock_code", "trade_date", name="uq_stock_daily_code_date"),
    )
    op.create_index("ix_stock_daily_stock_code", "stock_daily", ["stock_code"])
    op.create_index("ix_stock_daily_trade_date", "stock_daily", ["trade_date"])
