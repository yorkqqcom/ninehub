"""008: per-task Tushare collect param overrides."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "008_sync_task_collect_params"
down_revision: Union[str, None] = "007_drop_stock_daily"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sync_tasks",
        sa.Column("collect_params", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sync_tasks", "collect_params")
