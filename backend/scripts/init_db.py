"""Initialize PostgreSQL: create project user, database, and run migrations."""

import asyncio
import subprocess
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Superuser (local only — do not use in app runtime)
PG_HOST = "localhost"
PG_PORT = 5432
PG_SUPERUSER = "postgres"
PG_SUPERPASSWORD = "postgres"

# Project credentials (app uses these via .env)
PROJECT_USER = "ninehub"
PROJECT_PASSWORD = "ninehub_dev"
PROJECT_DB = "ninehub"


def create_user_and_database() -> None:
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_SUPERUSER,
        password=PG_SUPERPASSWORD,
        database="postgres",
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (PROJECT_USER,))
    if cur.fetchone() is None:
        cur.execute(
            sql.SQL("CREATE USER {} WITH PASSWORD %s").format(sql.Identifier(PROJECT_USER)),
            (PROJECT_PASSWORD,),
        )
        print(f"Created user: {PROJECT_USER}")
    else:
        cur.execute(
            sql.SQL("ALTER USER {} WITH PASSWORD %s").format(sql.Identifier(PROJECT_USER)),
            (PROJECT_PASSWORD,),
        )
        print(f"User exists, password updated: {PROJECT_USER}")

    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PROJECT_DB,))
    if cur.fetchone() is None:
        cur.execute(
            sql.SQL("CREATE DATABASE {} OWNER {}").format(
                sql.Identifier(PROJECT_DB),
                sql.Identifier(PROJECT_USER),
            )
        )
        print(f"Created database: {PROJECT_DB}")
    else:
        print(f"Database exists: {PROJECT_DB}")

    cur.close()
    conn.close()

    # Grant schema privileges (PostgreSQL 15+)
    app_conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_SUPERUSER,
        password=PG_SUPERPASSWORD,
        database=PROJECT_DB,
    )
    app_conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    app_cur = app_conn.cursor()
    app_cur.execute(
        sql.SQL("GRANT ALL ON SCHEMA public TO {}").format(sql.Identifier(PROJECT_USER))
    )
    app_cur.execute(
        sql.SQL("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {}").format(
            sql.Identifier(PROJECT_USER)
        )
    )
    app_cur.close()
    app_conn.close()
    print("Schema privileges granted.")


def write_env_file() -> None:
    env_path = BACKEND_ROOT / ".env"
    content = f"""# NineHub local development — app connects as project user (not postgres)
DATABASE_URL=postgresql+asyncpg://{PROJECT_USER}:{PROJECT_PASSWORD}@{PG_HOST}:{PG_PORT}/{PROJECT_DB}
SYNC_DATABASE_URL=postgresql+psycopg2://{PROJECT_USER}:{PROJECT_PASSWORD}@{PG_HOST}:{PG_PORT}/{PROJECT_DB}
SECRET_KEY=local-dev-secret-change-in-production
DEBUG=true
"""
    env_path.write_text(content, encoding="utf-8")
    print(f"Written {env_path}")


def run_alembic() -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT,
        check=True,
    )
    print("Alembic migrations applied.")


async def seed_admin() -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.core.security import get_password_hash
    from app.models.user import User

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.username == "admin"))
        if result.scalar_one_or_none():
            print("Admin user already exists (username: admin)")
        else:
            user = User(
                username="admin",
                hashed_password=get_password_hash("admin123456"),
                role="admin",
                is_active=True,
            )
            session.add(user)
            await session.commit()
            print("Created admin user: admin / admin123456")


def bootstrap_tia_doc_points() -> None:
    from app.services.tia.doc_points_bootstrap_service import ensure_doc_pages_cache_from_seeds

    result = ensure_doc_pages_cache_from_seeds(backend_root=BACKEND_ROOT)
    if result:
        print(
            f"Bootstrapped doc pages cache: {result['with_points']}/{result['merged']} with min_points"
        )
    else:
        print("Doc pages cache: already present")


def seed_default_tia_proposals() -> None:
    from sqlalchemy.orm import Session

    from app.core.database import sync_engine
    from app.services.tia.default_proposal_seed import seed_default_proposals_sync

    with Session(sync_engine) as session:
        created = seed_default_proposals_sync(session)
        session.commit()
        if created:
            print(f"Seeded {created} default TIA proposals from document/2 sidebar")
        else:
            print("Default TIA proposals: skipped (existing rows or missing bundle)")


def main() -> None:
    create_user_and_database()
    write_env_file()
    run_alembic()
    asyncio.run(seed_admin())
    bootstrap_tia_doc_points()
    seed_default_tia_proposals()
    print("\n--- Ready ---")
    print(f"DB: {PROJECT_DB} @ {PG_HOST}:{PG_PORT}")
    print(f"App user: {PROJECT_USER} (not postgres)")
    print("Login: admin / admin123456")
    print("Start: uvicorn app.main:app --reload --app-dir .")


if __name__ == "__main__":
    main()
