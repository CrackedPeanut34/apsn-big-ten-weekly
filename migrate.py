"""Applies db/migrations/*.sql in filename order, inside one transaction each.
Tracks applied filenames in a schema_migrations table so re-runs are safe.

Usage: python migrate.py
"""
import pathlib
import sys

import db

MIGRATIONS_DIR = pathlib.Path(__file__).parent / "db" / "migrations"


def main():
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        print("No migration files found.")
        return

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur.execute("SELECT filename FROM schema_migrations")
            applied = {row["filename"] for row in cur.fetchall()}

        for f in files:
            if f.name in applied:
                print(f"skip  {f.name} (already applied)")
                continue
            sql = f.read_text()
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (filename) VALUES (%s)", (f.name,)
                )
            conn.commit()
            print(f"apply {f.name}")

    print("done")


if __name__ == "__main__":
    sys.exit(main())
