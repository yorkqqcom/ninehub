"""009: manual min_points override on TIA proposals."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_proposal_min_points_override"
down_revision: Union[str, None] = "008_sync_task_collect_params"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tia_proposals",
        sa.Column("min_points_override", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tia_proposals", "min_points_override")
