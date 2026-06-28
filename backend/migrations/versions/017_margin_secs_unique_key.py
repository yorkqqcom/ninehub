"""017: margin_secs unique key must include exchange (SSE/SZSE/BSE per day)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017_margin_secs_unique_key"
down_revision: Union[str, None] = "016_forecast_reason_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_NAME = "uq_tushare_margin_secs_stock_code_trade_date"
NEW_NAME = "uq_tushare_margin_secs_stock_code_trade_date_exchange"
TABLE = "tushare_margin_secs"


def _drop_old_unique(inspector: sa.Inspector) -> None:
    for uc in inspector.get_unique_constraints(TABLE):
        cols = tuple(uc.get("column_names") or ())
        if cols == ("stock_code", "trade_date"):
            op.drop_constraint(uc["name"], TABLE, type_="unique")
            return
    for idx in inspector.get_indexes(TABLE):
        if idx.get("unique") and tuple(idx.get("column_names") or ()) == (
            "stock_code",
            "trade_date",
        ):
            op.drop_index(idx["name"], table_name=TABLE)


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if TABLE not in inspector.get_table_names():
        return

    _drop_old_unique(inspector)
    inspector = sa.inspect(conn)
    existing = {
        tuple(uc.get("column_names") or ())
        for uc in inspector.get_unique_constraints(TABLE)
    }
    if ("stock_code", "trade_date", "exchange") not in existing:
        op.create_unique_constraint(
            NEW_NAME,
            TABLE,
            ["stock_code", "trade_date", "exchange"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if TABLE not in inspector.get_table_names():
        return

    for uc in inspector.get_unique_constraints(TABLE):
        cols = tuple(uc.get("column_names") or ())
        if cols == ("stock_code", "trade_date", "exchange"):
            op.drop_constraint(uc["name"], TABLE, type_="unique")
            break

    existing = {
        tuple(uc.get("column_names") or ())
        for uc in inspector.get_unique_constraints(TABLE)
    }
    if ("stock_code", "trade_date") not in existing:
        op.create_unique_constraint(
            OLD_NAME,
            TABLE,
            ["stock_code", "trade_date"],
        )
