"""
benchmark.py

Runs the query benchmark against the loaded chat-history data.
Each query is warmed up, then run many times with different random
parameters; the median and 95th percentile latency are reported.
Results are printed and also saved to benchmark_results.md.
"""

import random
import re
import statistics
import time

from db import get_connection

SEED = 42
POINT_RUNS = 200      # repetitions for fast, indexed queries
HEAVY_RUNS = 5        # repetitions for full-table aggregations
WARMUP_RUNS = 10


def percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * pct))
    return ordered[index]


def measure(conn, sql: str, param_list: list[tuple]) -> dict:
    """Time one query over many parameter sets (milliseconds)."""
    # Warm-up runs fill the caches so the first call is not unfairly slow.
    for params in param_list[:WARMUP_RUNS]:
        conn.execute(sql, params).fetchall()

    timings, rows = [], 0
    for params in param_list:
        start = time.perf_counter()
        result = conn.execute(sql, params).fetchall()
        timings.append((time.perf_counter() - start) * 1000)
        rows += len(result)
    return {
        "runs": len(timings),
        "median_ms": statistics.median(timings),
        "p95_ms": percentile(timings, 0.95),
        "avg_rows": rows / len(timings),
    }


def main() -> None:
    random.seed(SEED)
    with get_connection() as conn:
        # Sample real values from the data so every query finds rows.
        conv_ids = [r[0] for r in conn.execute(
            "SELECT id FROM conversations ORDER BY random() LIMIT %s",
            (POINT_RUNS,)).fetchall()]
        user_count = conn.execute("SELECT count(*) FROM users").fetchone()[0]
        samples = [r[0] for r in conn.execute(
            "SELECT content FROM messages ORDER BY random() LIMIT 300"
        ).fetchall()]

        # Pick search terms from real messages (words of 4+ characters).
        terms = []
        for text in samples:
            words = re.findall(r"\w{4,}", text)
            if words:
                terms.append(random.choice(words))
        terms = terms[:POINT_RUNS]

        queries = [
            ("Read one full conversation in order",
             "SELECT seq, role, content FROM messages "
             "WHERE conversation_id = %s ORDER BY seq",
             [(c,) for c in conv_ids], POINT_RUNS),
            ("Last 10 messages of a conversation",
             "SELECT seq, role, content FROM messages "
             "WHERE conversation_id = %s ORDER BY seq DESC LIMIT 10",
             [(c,) for c in conv_ids], POINT_RUNS),
            ("20 newest conversations of a user",
             "SELECT id, title, created_at FROM conversations "
             "WHERE user_id = %s ORDER BY created_at DESC LIMIT 20",
             [(random.randint(1, user_count),) for _ in range(POINT_RUNS)],
             POINT_RUNS),
            ("Full-text search (first 20 hits)",
             "SELECT id FROM messages "
             "WHERE content_tsv @@ plainto_tsquery('simple', %s) LIMIT 20",
             [(t,) for t in terms], POINT_RUNS),
            ("JSONB filter on metadata (first 50 hits)",
             "SELECT id FROM messages WHERE metadata @> %s::jsonb LIMIT 50",
             [(f'{{"tokens": {random.randint(5, 800)}}}',)
              for _ in range(POINT_RUNS)], POINT_RUNS),
            ("Messages per day (full-table aggregation)",
             "SELECT date_trunc('day', created_at) AS day, count(*) "
             "FROM messages GROUP BY day ORDER BY day",
             [()] * HEAVY_RUNS, HEAVY_RUNS),
        ]

        lines = ["| Query | Runs | Median (ms) | p95 (ms) | Avg rows |",
                 "|---|---|---|---|---|"]
        for name, sql, params, _ in queries:
            res = measure(conn, sql, params)
            line = (f"| {name} | {res['runs']} | {res['median_ms']:.2f} | "
                    f"{res['p95_ms']:.2f} | {res['avg_rows']:.1f} |")
            lines.append(line)
            print(line)
    with open("benchmark_results.md", "w", encoding="utf-8") as f:
        f.write("# Benchmark results\n\n" + "\n".join(lines) + "\n")
    print("Saved to benchmark_results.md")


if __name__ == "__main__":
    main()