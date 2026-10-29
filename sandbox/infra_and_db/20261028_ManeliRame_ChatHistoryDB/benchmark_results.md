# Benchmark results

| Query | Runs | Median (ms) | p95 (ms) | Avg rows |
|---|---|---|---|---|
| Read one full conversation in order | 200 | 0.35 | 0.48 | 11.8 |
| Last 10 messages of a conversation | 200 | 0.25 | 0.38 | 8.8 |
| 20 newest conversations of a user | 200 | 0.31 | 0.53 | 18.1 |
| Full-text search (first 20 hits) | 200 | 1.17 | 2.37 | 19.7 |
| JSONB filter on metadata (first 50 hits) | 200 | 0.64 | 1.32 | 50.0 |
| Messages per day (full-table aggregation) | 5 | 151.24 | 159.56 | 201.0 |
