"""
db.py

Shared database connection helper for the chat-history PoC.
Connection settings are read from the .env file, so no credentials
are ever hardcoded in the source code.
"""

import os

import psycopg
from dotenv import load_dotenv


def get_connection() -> psycopg.Connection:
    """Open a new PostgreSQL connection using the values in .env."""
    # Load the variables from .env into the process environment.
    load_dotenv()
    return psycopg.connect(
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        dbname=os.environ["DB_NAME"],
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
    )