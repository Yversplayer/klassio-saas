"""KLASSIO — génère `backend/schema_postgres.sql` depuis `backend/schema.sql`.

Le schéma PostgreSQL n'est jamais écrit à la main : il est dérivé du schéma
SQLite qui fait foi. Une divergence entre les deux serait une source de bogues
silencieux au moment de la bascule.

    python backend/tools/pg_schema.py
"""
import os
import sys

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, BACKEND)
import sql_dialect  # noqa: E402

SOURCE = os.path.join(BACKEND, "schema.sql")
TARGET = os.path.join(BACKEND, "schema_postgres.sql")
HEADER = (
    "-- KLASSIO — schéma PostgreSQL, GÉNÉRÉ depuis schema.sql.\n"
    "-- Ne pas éditer à la main : régénérer avec `python backend/tools/pg_schema.py`.\n\n"
)


def main():
    with open(SOURCE, "r", encoding="utf-8") as f:
        source = f.read()
    try:
        ddl = sql_dialect.schema_to_postgres(source)
    except ValueError as e:
        print(f"Traduction impossible : {e}")
        return 1
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(HEADER + ddl)
    print(f"{TARGET}")
    print(f"  {ddl.count('CREATE TABLE')} tables, "
          f"{ddl.count('CREATE INDEX') + ddl.count('CREATE UNIQUE INDEX')} index")
    return 0


if __name__ == "__main__":
    sys.exit(main())
