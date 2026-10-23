# Normalizer Agent — Iman Abedini

LLM-based normalizer agent for Iranian job-advertisement field values.

Deterministic-first pipeline (Unicode unification, Persian/Arabic character
normalization, unit conversion, vocabulary lookups) with a provider-agnostic
LLM fallback layer for unresolved values. Outputs a strict `JobAd` schema
with audit trail, human-review flags, and usage statistics.

**Status:** test upload — the full project code and docs will follow in the
next PR under this same folder.

## Planned contents

- `src/normalizer_agent/` — pipeline, rules, LLM providers, schemas
- `config/` — `llm.yaml`, `fields.yaml`, `pipeline.yaml`, vocabulary CSVs
- `tests/` — unit + golden-value tests, 5 synthetic sample records
- `docs/` — architecture and integration documents
