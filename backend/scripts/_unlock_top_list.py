"""Terminate blocking sessions on tushare_top_list."""
from sqlalchemy import text

from app.core.database import SyncSessionLocal


def main() -> None:
    session = SyncSessionLocal()
    try:
        blockers = session.execute(
            text(
                """
                SELECT pid, state, query
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid <> pg_backend_pid()
                  AND (
                    query ILIKE '%tushare_top_list%'
                    OR query ILIKE '%TRUNCATE%'
                  )
                """
            )
        ).fetchall()
        print("candidates:", len(blockers))
        for pid, state, query in blockers:
            print(f" terminate {pid} {state}: {(query or '')[:80]}")
            session.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    main()
