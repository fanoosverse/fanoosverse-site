# Architecture Document: LLM Chat History Storage

This document explains which database and which validation approach we chose for storing, validating and querying LLM chat history, why we chose them, and what the proof of concept (PoC) measured. All numbers in the benchmark section come from a real run of `benchmark.py`.

## 1. Scenario and requirements

An LLM chat product stores conversations. Each conversation belongs to one user and holds an ordered list of messages (system, user, assistant, tool). The access patterns we expect:

| Pattern | Frequency | Needs |
|---|---|---|
| Open a conversation and read all messages in order | Very high | Fast lookup by conversation, strict ordering |
| Show the latest messages of a conversation | Very high | Fast reverse-ordered read with a limit |
| List a user's recent conversations | High | Index by user and time |
| Search message text | Medium | Full-text search, Persian and English |
| Filter by message metadata (tokens, latency, tool calls) | Medium | Flexible, schema-light fields |
| Analytics (messages per day, token usage) | Low | Aggregation over the whole table |
| Write new messages | Very high | Append-only, ordered, consistent |

Data characteristics: highly structured core (ids, roles, order, timestamps), a variable part (metadata that changes as models and tools change), long free text, and a strong need for integrity (a message must never point to a missing conversation or have an invalid role).

## 2. Database choice: PostgreSQL with JSONB

We chose **PostgreSQL**, keeping the stable core in normal columns and the variable part in a **JSONB** column.

Reasons:

1. **The core is relational.** Users, conversations and messages have fixed relationships. Foreign keys, `NOT NULL`, `CHECK` constraints and a unique `(conversation_id, seq)` pair give us integrity guarantees directly in the database.
2. **The variable part fits JSONB.** Token counts, latency, tool-call details and model parameters change over time. JSONB stores them without schema migrations and can be indexed (GIN with `jsonb_path_ops`).
3. **One system covers most needs.** Full-text search (`tsvector` with a GIN index), JSON filtering, time-range scans (BRIN index) and analytics all work in the same engine, so we avoid running and synchronizing several databases.
4. **Transactions.** Appending a message and updating conversation state can be atomic.
5. **Growth path.** Time-based table partitioning, read replicas and, if semantic search is needed later, a vector extension (pgvector) can be added without changing the model.

### Alternatives considered (reasoned comparison, not measured in this PoC)

| Option | Why we did not choose it as the primary store |
|---|---|
| Document database (e.g. MongoDB) | Natural fit for nested conversations, but weaker built-in integrity (no foreign keys), and cross-conversation queries and analytics need more work. Embedding all messages in one document also hits size limits for very long chats. |
| Key-value or wide-column store (e.g. Redis, Cassandra) | Excellent for fast reads by key, but poor for search, filtering and ad-hoc queries. Better as a cache in front of the main store. |
| Columnar analytics database (e.g. ClickHouse) | Very fast aggregations, but not designed for frequent point lookups and row-level consistency. Better as a secondary analytics store fed from PostgreSQL. |
| Vector database | Only useful for semantic search over messages. It does not replace the system of record. |
| SQLite | Great for local testing, but a single-writer file database is not suitable for a multi-user service. |

We did not benchmark these alternatives in this PoC. The comparison above is a design argument, and a follow-up PoC could measure MongoDB on the same data if the team wants numbers.

## 3. Schema design

Defined in `schema.sql`:

- `users`: identity of the owner.
- `conversations`: UUID primary key, owner, title (1 to 200 characters), model name, creation time.
- `messages`: UUID primary key, `conversation_id` (foreign key, cascade delete), `seq` (position in the conversation, 0 or more), `role` (restricted to four values), `content` (non-empty), `metadata` (JSONB), `created_at`, and a generated `content_tsv` column for text search.

Indexing decisions:

| Index | Purpose |
|---|---|
| `UNIQUE (conversation_id, seq)` | Guarantees one message per position and serves "read a conversation in order" and "last N messages". |
| `(user_id, created_at DESC)` on conversations | Lists a user's newest conversations without sorting. |
| GIN on `content_tsv` | Full-text search. |
| GIN `jsonb_path_ops` on `metadata` | Containment filters on metadata. |
| BRIN on `messages.created_at` | Tiny index for time-range scans, effective because rows are inserted roughly in time order. |

Note on language: PostgreSQL has no built-in Persian stemmer, so the `simple` text search configuration is used. It tokenizes Persian text correctly but does no stemming, so searching a word will not match its other inflected forms.

## 4. Validation approach: two layers

**Layer 1: Pydantic v2 models (`models.py`), before the data reaches the database.**
It checks types, allowed roles (a `Literal`), non-empty content with a maximum length, non-negative `seq`, valid UUIDs, timezone-aware timestamps, and it rejects unknown fields (`extra="forbid"`). Reasons for choosing it: errors are fast and descriptive, rules are written as code that is easy to review and test, and the same models can be reused in an API layer.

**Layer 2: database constraints (`schema.sql`), the last line of defense.**
`CHECK`, `NOT NULL`, foreign keys and unique constraints protect the data even if some other tool or script writes to the database and skips the application layer.

Why two layers: the first gives early, friendly errors and keeps bad data away from the database. The second guarantees integrity no matter which client writes. Neither alone is enough.

The PoC demonstrates layer 1 with five deliberately invalid records (unknown role, empty content, negative sequence number, timestamp without timezone, extra field). All five were rejected.

## 5. PoC description

| File | Role |
|---|---|
| `schema.sql`, `init_db.py` | Create tables, constraints and indexes. |
| `models.py` | Validation layer 1. |
| `load_data.py` | Generates mock data, validates every record, bulk-loads with `COPY`. |
| `benchmark.py` | Runs the query benchmark and writes `benchmark_results.md`. |
| `db.py` | Connection helper; credentials come only from `.env`. |

Dataset in the measured run: **1,000 users, 20,000 conversations, 238,742 messages**. Mock text is randomly generated sentences, half Persian and half English, with a fixed random seed for repeatability.

## 6. Benchmark results

Method: each query is warmed up, then run with different random parameters sampled from the real data. Latency is measured in the Python client with `time.perf_counter`, so it includes the round trip to a local database. We report the median and the 95th percentile (p95).

| Query | Runs | Median (ms) | p95 (ms) | Avg rows |
|---|---|---|---|---|
| Read one full conversation in order | 200 | 0.35 | 0.48 | 11.8 |
| Last 10 messages of a conversation | 200 | 0.25 | 0.38 | 8.8 |
| 20 newest conversations of a user | 200 | 0.31 | 0.53 | 18.1 |
| Full-text search (first 20 hits) | 200 | 1.17 | 2.37 | 19.7 |
| JSONB filter on metadata (first 50 hits) | 200 | 0.64 | 1.32 | 50.0 |
| Messages per day (full-table aggregation) | 5 | 151.24 | 159.56 | 201.0 |

Test environment: Lenovo ThinkPad laptop, Intel Core i5-1135G7 (11th generation) CPU, 16 GB DDR4 RAM, 512 GB NVMe SSD, Windows, PostgreSQL 17 running locally on the same machine as the benchmark client.

### Interpretation

- The three hot-path queries (read a conversation, read the latest messages, list a user's conversations) all finish in well under one millisecond at the median, which matches the design goal for the most frequent operations.
- Full-text search and JSONB filtering stay in the low-millisecond range thanks to their GIN indexes. Both queries stop at the first 20 or 50 hits, so they show the cost of finding matches, not of returning every match.
- The full-table aggregation takes about 150 ms for 238 thousand messages. This is expected for a scan, and it will grow roughly linearly with table size.

### Limitations of this PoC (important)

1. **Small dataset.** About 239 thousand messages fits comfortably in memory. Production volumes are orders of magnitude larger, and cold-cache or disk-bound behavior was not tested.
2. **Local database, single client.** There was no network latency and no concurrent load, so throughput under many simultaneous users is unknown.
3. **Mock text.** Randomly generated sentences are shorter and less varied than real chats, which affects full-text search timing and index size.
4. **Warm cache.** Results reflect warmed-up queries.
5. **Alternatives were not measured.** The comparison in section 2 is a reasoned argument.

## 7. Scaling notes (not implemented in the PoC)

- Partition `messages` by month once the table reaches hundreds of millions of rows, so old partitions can be archived and scans stay small.
- For heavy analytics, either precompute daily rollups or replicate data to a columnar store instead of scanning the raw table.
- Add pgvector if semantic search over messages becomes a requirement.
- Consider a stemming or Persian-aware search solution if the `simple` configuration proves too limited.

## 8. Reproducing the results

1. Install PostgreSQL and create an empty database.
2. Copy `.env.example` to `.env` and fill in the connection values.
3. Run `pip install pydantic faker python-dotenv "psycopg[binary]"`.
4. Run `python init_db.py`, then `python load_data.py`, then `python benchmark.py`.
