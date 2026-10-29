# Chat History Database PoC

Proof of concept for storing, validating and querying LLM chat history in PostgreSQL. The reasoning behind every choice is in `ARCHITECTURE.md`.

## Scripts

| File | Purpose |
|---|---|
| `schema.sql` | Tables, constraints and indexes (second validation layer). |
| `db.py` | Connection helper. Reads credentials from `.env`. |
| `init_db.py` | Applies `schema.sql`. Safe to run repeatedly. |
| `models.py` | Pydantic models (first validation layer). |
| `load_data.py` | Generates mock data, validates it, bulk-loads it with `COPY`. Empties the tables on every run. |
| `benchmark.py` | Runs the query benchmark and writes `benchmark_results.md`. |

## Setup

1. Install PostgreSQL and create an empty database.
2. Copy `.env.example` to `.env` and fill in your connection values. Never commit `.env`; it is listed in `.gitignore`.
3. Install the dependencies:

```
pip install pydantic faker python-dotenv "psycopg[binary]"
```

## Run order

```
python init_db.py
python load_data.py
python benchmark.py
```

Dataset size can be changed through the constants at the top of `load_data.py`.
