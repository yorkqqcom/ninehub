"""014: allow null end_date on tushare_stk_managers (incumbent managers)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_managers_null_end"
down_revision: Union[str, None] = "013_manager_rewards_unique_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "tushare_stk_managers" not in inspector.get_table_names():
        return
    cols = {c["name"]: c for c in inspector.get_columns("tushare_stk_managers")}
    if "end_date" in cols and not cols["end_date"].get("nullable", True):
        op.alter_column("tushare_stk_managers", "end_date", existing_type=sa.Date(), nullable=True)


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "tushare_stk_managers" not in inspector.get_table_names():
        return
    cols = {c["name"]: c for c in inspector.get_columns("tushare_stk_managers")}
    if "end_date" in cols and cols["end_date"].get("nullable", False):
        op.alter_column("tushare_stk_managers", "end_date", existing_type=sa.Date(), nullable=False)
