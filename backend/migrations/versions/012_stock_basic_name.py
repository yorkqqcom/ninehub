"""012: add name column to tushare_stock_basic for browser 证券简称."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012_stock_basic_name"
down_revision: Union[str, None] = "011_browser_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "tushare_stock_basic" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("tushare_stock_basic")}
    if "name" not in cols:
        op.add_column("tushare_stock_basic", sa.Column("name", sa.String(length=128), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "tushare_stock_basic" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("tushare_stock_basic")}
    if "name" in cols:
        op.drop_column("tushare_stock_basic", "name")
