"""
init_db.py

Creates the tables, constraints and indexes by running schema.sql.
Safe to run more than once, because the schema uses IF NOT EXISTS.
"""

from pathlib import Path

from db import get_connection

# schema.sql lives next to this script.
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def main() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    # The connection context manager commits automatically on success.
    with get_connection() as conn:
        conn.execute(sql)
    print("Schema applied successfully.")


main()