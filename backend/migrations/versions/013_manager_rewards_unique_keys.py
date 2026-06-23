"""013: fix unique keys for stk_managers (incumbent end_date null) and stk_rewards."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_manager_rewards_unique_keys"
down_revision: Union[str, None] = "012_stock_basic_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _drop_uq(inspector: sa.Inspector, table: str, columns: tuple[str, ...]) -> None:
    for uc in inspector.get_unique_constraints(table):
        if tuple(uc.get("column_names") or ()) == columns:
            op.drop_constraint(uc["name"], table, type_="unique")
            return


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if "tushare_stk_managers" in tables:
        _drop_uq(inspector, "tushare_stk_managers", ("stock_code", "end_date"))
        existing = {
            tuple(uc.get("column_names") or ())
            for uc in inspector.get_unique_constraints("tushare_stk_managers")
        }
        if ("stock_code", "title", "begin_date") not in existing:
            op.create_unique_constraint(
                "uq_tushare_stk_managers_stock_code_title_begin_date",
                "tushare_stk_managers",
                ["stock_code", "title", "begin_date"],
            )

    if "tushare_stk_rewards" in tables:
        _drop_uq(inspector, "tushare_stk_rewards", ("stock_code", "end_date"))
        existing = {
            tuple(uc.get("column_names") or ())
            for uc in inspector.get_unique_constraints("tushare_stk_rewards")
        }
        if ("stock_code", "end_date", "title") not in existing:
            op.create_unique_constraint(
                "uq_tushare_stk_rewards_stock_code_end_date_title",
                "tushare_stk_rewards",
                ["stock_code", "end_date", "title"],
            )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if "tushare_stk_managers" in tables:
        _drop_uq(inspector, "tushare_stk_managers", ("stock_code", "title", "begin_date"))
        existing = {
            tuple(uc.get("column_names") or ())
            for uc in inspector.get_unique_constraints("tushare_stk_managers")
        }
        if ("stock_code", "end_date") not in existing:
            op.create_unique_constraint(
                "uq_tushare_stk_managers_stock_code_end_date",
                "tushare_stk_managers",
                ["stock_code", "end_date"],
            )

    if "tushare_stk_rewards" in tables:
        _drop_uq(inspector, "tushare_stk_rewards", ("stock_code", "end_date", "title"))
        existing = {
            tuple(uc.get("column_names") or ())
            for uc in inspector.get_unique_constraints("tushare_stk_rewards")
        }
        if ("stock_code", "end_date") not in existing:
            op.create_unique_constraint(
                "uq_tushare_stk_rewards_stock_code_end_date",
                "tushare_stk_rewards",
                ["stock_code", "end_date"],
            )
