"""Create NineHub PostgreSQL user and database (run as superuser)."""

import sys

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

PG_HOST = "localhost"
PG_PORT = 5432
PG_SUPERUSER = "postgres"
PG_SUPERPASS = "postgres"
APP_USER = "ninehub"
APP_PASS = "ninehub"
APP_DB = "ninehub"


def main() -> None:
    print(f"Connecting to PostgreSQL at {PG_HOST}:{PG_PORT} as {PG_SUPERUSER}...")
    conn = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_SUPERUSER,
        password=PG_SUPERPASS,
        dbname="postgres",
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()

    cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (APP_USER,))
    if cur.fetchone():
        print(f"User '{APP_USER}' already exists.")
    else:
        cur.execute(f"CREATE USER {APP_USER} WITH PASSWORD %s", (APP_PASS,))
        print(f"Created user '{APP_USER}'.")

    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (APP_DB,))
    if cur.fetchone():
        print(f"Database '{APP_DB}' already exists.")
    else:
        cur.execute(f"CREATE DATABASE {APP_DB} OWNER {APP_USER}")
        print(f"Created database '{APP_DB}'.")

    cur.close()
    conn.close()

    conn2 = psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_SUPERUSER,
        password=PG_SUPERPASS,
        dbname=APP_DB,
    )
    conn2.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cur2 = conn2.cursor()
    cur2.execute(f"GRANT ALL ON SCHEMA public TO {APP_USER}")
    cur2.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO {APP_USER}")
    cur2.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO {APP_USER}")
    cur2.close()
    conn2.close()

    print("PostgreSQL setup complete.")
    print(f"  database: {APP_DB}")
    print(f"  user:     {APP_USER}")
    print(f"  password: {APP_PASS}")


if __name__ == "__main__":
    try:
        main()
    except psycopg2.Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
