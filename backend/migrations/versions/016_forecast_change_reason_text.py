"""016: widen tushare_forecast.change_reason to TEXT (long disclosure text)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "016_forecast_reason_text"
down_revision: Union[str, None] = "015_holder_name_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _widen_to_text(table: str, column: str) -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if table not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns(table)}
    if column not in cols:
        return
    op.alter_column(
        table,
        column,
        existing_type=sa.String(length=128),
        type_=sa.Text(),
        existing_nullable=True,
    )


def upgrade() -> None:
    _widen_to_text("tushare_forecast", "change_reason")


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "tushare_forecast" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("tushare_forecast")}
    if "change_reason" not in cols:
        return
    op.alter_column(
        "tushare_forecast",
        "change_reason",
        existing_type=sa.Text(),
        type_=sa.String(length=128),
        existing_nullable=True,
    )
