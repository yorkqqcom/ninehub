"""Fix top_list unique key and print table counts."""
from sqlalchemy import text

from app.core.database import SyncSessionLocal


def main() -> None:
    session = SyncSessionLocal()
    try:
        rows = session.execute(
            text(
                "SELECT conname FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "WHERE t.relname = 'tushare_top_list' AND c.contype = 'u'"
            )
        ).fetchall()
        print("constraints:", [r[0] for r in rows])

        if any(r[0] == "uq_tushare_top_list_trade_date" for r in rows):
            session.execute(
                text(
                    "ALTER TABLE tushare_top_list "
                    "DROP CONSTRAINT uq_tushare_top_list_trade_date"
                )
            )
            print("dropped uq_tushare_top_list_trade_date")

        names = {r[0] for r in session.execute(
            text(
                "SELECT conname FROM pg_constraint c "
                "JOIN pg_class t ON c.conrelid = t.oid "
                "WHERE t.relname = 'tushare_top_list' AND c.contype = 'u'"
            )
        ).fetchall()}
        if "uq_tushare_top_list_stock_code_trade_date" not in names:
            session.execute(
                text(
                    "ALTER TABLE tushare_top_list ADD CONSTRAINT "
                    "uq_tushare_top_list_stock_code_trade_date "
                    "UNIQUE (stock_code, trade_date)"
                )
            )
            print("added uq_tushare_top_list_stock_code_trade_date")
        session.commit()

        for table in (
            "tushare_top_list",
            "tushare_margin",
            "tushare_block_trade",
            "tushare_weekly",
        ):
            cnt = session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"{table}: {cnt}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
