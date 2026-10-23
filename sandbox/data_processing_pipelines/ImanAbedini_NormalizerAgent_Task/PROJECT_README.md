# Fanos Normalizer Agent

Production-grade, provider-agnostic normalizer agent for the Fanos Iranian
job-market intelligence pipeline. It takes raw job-advertisement records
approved by the Extractor/Supervisor, canonicalizes every field value to
project standards, and emits a strict `JobAd` model wrapped in an envelope
with audit trail, human-review items, usage statistics, and status codes.

```
raw JobAdRaw ─▶ intake ─▶ deterministic rules ─▶ vocabulary lookup ─▶ LLM (unresolved only) ─▶ validation ─▶ JobAd + envelope
```

## Key features

- **Deterministic-first.** Persian/Arabic character unification (`ي→ی`,
  `ك→ک`, tatweel, ZWNJ), Persian digit and number-word parsing, Jalali→
  Gregorian date conversion (33-year cycle arithmetic), toman→IRR (×10)
  conversion, placeholder removal, and composite splitting with a whitelist
  (`CI/CD`, `A/B Testing`, …) all happen **before** any LLM call. Models are
  only consulted for what rules and vocabularies cannot resolve — typically
  one request per record.
- **Provider-agnostic.** Works with `Anthropic Claude`, any
  OpenAI-compatible endpoint (vLLM, Ollama, DeepSeek, Qwen/DashScope, GLM,
  Gemini-compat), and a network-free `mock` provider for tests. Switching
  models or providers is a pure `config/llm.yaml` edit — no vendor SDK or
  model name lives outside `llm/providers/`.
- **Resilient by design.** Priority fallback with round-robin rotation,
  exponential backoff with jitter, `Retry-After` handling, permanent-error
  detection (401/403/404/400 skip retries), per-provider circuit breakers,
  and sliding-window rate limiting.
- **Persistent LLM cache.** SQLite cache keyed by
  `(field_kind, raw_value, vocab_version, prompt_version, llm_mode)` — a
  cache hit skips the LLM entirely, so re-runs on the same data cost
  nothing.
- **Provenance protection.** `document_id`, `collector`, `source_type`,
  `text`, `content_hash`, `source_date`, `collected_at`, `version` are never
  modified. English output everywhere; Persian survives only in raw and
  provenance fields.
- **Never guesses.** If a value cannot be mapped confidently, no canonical
  value is invented: the item is flagged for human review and (for
  skill-like fields) recorded in `candidate_new_skill` for vocabulary
  growth.
- **Full audit trail.** Every emitted value records its raw input,
  canonical output, resolution method (`rule` / `lookup` / `llm` /
  `cache`), confidence, provider, model, and vocabulary version. Review
  items carry machine-readable reasons (`not_in_vocabulary`,
  `low_confidence`, `inferred`, `validation_failed`).
- **Schema-driven.** Field behavior lives in `config/fields.yaml` — kinds
  (`vocab_list`, `enum_single`, `money`, `integer_range_min`, …), pairings,
  and ranges — so schema changes need no code changes.

## Installation

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate        # Linux / macOS
.venv\Scripts\activate           # Windows

pip install -e .
# with the FastAPI microservice and dev tooling:
pip install -e ".[service,dev]"
```

Secrets come only from environment variables — copy `.env.example` to
`.env` and fill in the keys for the providers you actually use. API keys are
never logged, and full ad `text` is never logged at INFO level.

```bash
cp .env.example .env
```

## CLI

```bash
# validate llm.yaml / fields.yaml / pipeline.yaml and their consistency
normalizer validate-config -c config

# probe every enabled provider with a live request
normalizer llm-check -c config

# normalize records (single JSON object, a JSON array, or JSONL)
normalizer run --input raw.jsonl --output normalized.jsonl -c config
```

Every input record produces one output envelope: `status`
(`normalized` / `needs_review` / `failed` / `rejected`), the strict `JobAd`
when it validates, `error_codes`, `review_items`, per-field `audit`,
`usage` (tokens and estimated cost), and `versions` of normalizer, prompt,
and every vocabulary involved.

## Python API

```python
from normalizer_agent.interface.api import Normalizer

normalizer = await Normalizer.from_config("config")
result = await normalizer.normalize(raw_record, record_id="rec_001")
if result.status == "needs_review":
    for item in result.review_items:
        print(item.field, item.raw, item.reason)
```

## REST microservice (optional)

```bash
uvicorn normalizer_agent.interface.service:create_app --factory --port 8000
```

| Endpoint | Purpose |
|---|---|
| `POST /normalize` | normalize one record |
| `POST /normalize/batch` | normalize a list of records |
| `GET /health` | liveness + enabled providers |
| `GET /metrics` | pipeline counters (rule/lookup/llm/cache/review items, tokens, cost) |

## Configuration layout

| Path | Contents |
|---|---|
| `config/llm.yaml` | providers, priorities, retries, timeouts, costs, routing strategy |
| `config/fields.yaml` | per-field normalization behavior (kind, vocab, pair, range) |
| `config/pipeline.yaml` | thresholds, LLM mode (`direct`/`candidates`/`full_list`), cache, circuit breaker, concurrency |
| `config/vocab/*.csv` | canonical vocabularies with Persian/English variants (`value,category,variants`) |
| `prompts/*.md` | versioned prompt templates (`normalize_values.v1.md`, `repair_output.v1.md`) |

## Tests

```bash
pytest            # 134 tests: text, rules, vocab, LLM layer, pipeline, interfaces, golden values
ruff check src tests
mypy              # strict mode, zero errors
```

The golden suite (`tests/data/golden_values.csv`) pins ~50 raw→canonical
pairs (skills, employment types, salary strings, experience phrasings) and
`tests/data/sample_record_*.json` provides five realistic synthetic ads
exercising the full pipeline end to end.

## Project structure

```
src/normalizer_agent/
├── settings.py            # YAML loading + validation, FieldRule model
├── startup_check.py       # cross-file consistency checks
├── text/                  # unification, placeholders, composite splitting
├── rules/                 # numbers, money, dates (Jalali), naming checks
├── vocab/                 # CSV vocabulary store + trigram fuzzy retriever
├── llm/                   # FallbackRouter, circuit breaker, rate limiter
│   └── providers/         # anthropic, openai_compat, mock
├── cache/                 # SQLite result cache
├── pipeline/              # collector, deterministic resolver, LLM stage, orchestrator
├── validate/              # post-LLM deterministic checks
├── review/                # human-review sink interface
├── schemas/               # JobAdRaw (permissive) / JobAd (strict) / envelope
├── observability/         # structured logging, metrics
└── interface/             # CLI, Python API facade, coordinator adapter, FastAPI
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design and data flow
- [docs/INTEGRATION.md](docs/INTEGRATION.md) — wiring into the Fanos pipeline
- [docs/ADDING_A_PROVIDER.md](docs/ADDING_A_PROVIDER.md) — adding a new LLM provider
- [docs/CHANGING_THE_SCHEMA.md](docs/CHANGING_THE_SCHEMA.md) — evolving fields and vocabularies
- [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) — design assumptions and trade-offs

## License

Internal component of the Fanos project.
