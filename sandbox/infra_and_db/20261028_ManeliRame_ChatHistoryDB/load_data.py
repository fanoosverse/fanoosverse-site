"""
load_data.py

Generates mock chat history, validates every record with the Pydantic
models, then bulk-loads the valid records into PostgreSQL using COPY.
Also feeds a few deliberately invalid records to show that the
validation layer rejects them.

WARNING: every run empties the tables first, so runs are repeatable.
"""

import json
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

from faker import Faker
from pydantic import ValidationError

from db import get_connection
from models import ConversationIn, MessageIn

# ---- Dataset size settings (change these to scale the test) ----
NUM_USERS = 1000
NUM_CONVERSATIONS = 20000
MIN_MESSAGES = 4
MAX_MESSAGES = 20
SEED = 42
MODELS = ["model-small", "model-medium", "model-large"]


def build_sentence_pool(size: int = 2000) -> list[str]:
    """Pre-generate sentences once; picking from a pool is far faster
    than calling Faker for every message."""
    Faker.seed(SEED)
    persian = Faker("fa_IR")
    english = Faker("en_US")
    pool = []
    for i in range(size):
        words = random.randint(5, 25)
        faker = persian if i % 2 == 0 else english
        pool.append(faker.sentence(nb_words=words))
    return pool


def generate_valid_records(pool: list[str]):
    """Create conversations and messages, validating each record."""
    conversations, messages = [], []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    for _ in range(NUM_CONVERSATIONS):
        conv_id = uuid.uuid4()
        start = base + timedelta(seconds=random.randint(0, 200 * 24 * 3600))
        conv = ConversationIn.model_validate({
            "id": conv_id,
            "user_id": random.randint(1, NUM_USERS),
            "title": random.choice(pool)[:60],
            "model": random.choice(MODELS),
            "created_at": start,
        })
        conversations.append(conv)

        # Alternate user/assistant turns, numbered from zero.
        for seq in range(random.randint(MIN_MESSAGES, MAX_MESSAGES)):
            role = "user" if seq % 2 == 0 else "assistant"
            meta = {"tokens": random.randint(5, 800)}
            if role == "assistant":
                meta["latency_ms"] = random.randint(200, 5000)
            messages.append(MessageIn.model_validate({
                "id": uuid.uuid4(),
                "conversation_id": conv_id,
                "seq": seq,
                "role": role,
                "content": random.choice(pool),
                "metadata": meta,
                "created_at": start + timedelta(seconds=seq * 20),
            }))
    return conversations, messages


def run_invalid_record_demo() -> None:
    """Show that bad records are rejected by the validation layer."""
    now = datetime.now(timezone.utc)
    good = {"id": uuid.uuid4(), "conversation_id": uuid.uuid4(), "seq": 0,
            "role": "user", "content": "hello", "created_at": now}
    bad_cases = {
        "unknown role": {**good, "role": "admin"},
        "empty content": {**good, "content": "   "},
        "negative seq": {**good, "seq": -1},
        "naive timestamp": {**good, "created_at": datetime(2026, 1, 1)},
        "extra field": {**good, "hack": "x"},
    }
    rejected = 0
    for name, record in bad_cases.items():
        try:
            MessageIn.model_validate(record)
            print(f"  NOT rejected (unexpected): {name}")
        except ValidationError as err:
            rejected += 1
            print(f"  rejected [{name}]: {err.errors()[0]['msg']}")
    print(f"Invalid records rejected: {rejected}/{len(bad_cases)}")


def load_into_database(conversations, messages) -> None:
    with get_connection() as conn:
        # Start from a clean state so every run is comparable.
        conn.execute(
            "TRUNCATE users, conversations, messages RESTART IDENTITY CASCADE")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO users (username) VALUES (%s)",
                [(f"user_{i}",) for i in range(1, NUM_USERS + 1)])
# COPY is the fastest way to bulk-load rows into PostgreSQL.
            with cur.copy(
                "COPY conversations (id, user_id, title, model, created_at) "
                "FROM STDIN"
            ) as copy:
                for c in conversations:
                    copy.write_row(
                        (str(c.id), c.user_id, c.title, c.model, c.created_at))

            with cur.copy(
                "COPY messages (id, conversation_id, seq, role, content, "
                "metadata, created_at) FROM STDIN"
            ) as copy:
                for m in messages:
                    copy.write_row((
                        str(m.id), str(m.conversation_id), m.seq, m.role,
                        m.content, json.dumps(m.metadata), m.created_at))

        # Refresh planner statistics so the benchmark is fair.
        conn.execute("ANALYZE")


def main() -> None:
    random.seed(SEED)
    pool = build_sentence_pool()

    t0 = time.perf_counter()
    conversations, messages = generate_valid_records(pool)
    t1 = time.perf_counter()
    print(f"Generated + validated {len(conversations)} conversations "
          f"and {len(messages)} messages in {t1 - t0:.1f}s")

    print("Validation demo with invalid records:")
    run_invalid_record_demo()

    load_into_database(conversations, messages)
    t2 = time.perf_counter()
    print(f"Bulk load finished in {t2 - t1:.1f}s")


if __name__ == "__main__":
    main()