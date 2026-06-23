"""015: widen tushare_stk_holdertrade.holder_name to TEXT (multi-holder names)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015_holder_name_text"
down_revision: Union[str, None] = "014_managers_null_end"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "tushare_stk_holdertrade" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("tushare_stk_holdertrade")}
    if "holder_name" not in cols:
        return
    op.alter_column(
        "tushare_stk_holdertrade",
        "holder_name",
        existing_type=sa.String(length=128),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "tushare_stk_holdertrade" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("tushare_stk_holdertrade")}
    if "holder_name" not in cols:
        return
    op.alter_column(
        "tushare_stk_holdertrade",
        "holder_name",
        existing_type=sa.Text(),
        type_=sa.String(length=128),
        existing_nullable=True,
    )
