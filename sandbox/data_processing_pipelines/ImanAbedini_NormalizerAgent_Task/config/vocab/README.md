# Controlled vocabularies

CSV files, UTF-8, three columns:

```
value,category,variants(|-separated)
```

- `value`: the canonical form (English; Title Case for concepts, snake_case is never stored here — enum members come from the Python schema, the variants column maps Persian phrases to them).
- `category`: optional tag (`tool`, `soft_skill`, `city`, ...).
- `variants`: pipe-separated alternative spellings in any language, e.g. `پایتون|py|python3`.

Rules:
- The file name is the vocabulary name referenced from `config/fields.yaml` (`vocab: capability` → `capability.csv`).
- The vocabulary may be empty/partial: unresolved values go to the LLM and its proposals are flagged for review.
- The version of a vocabulary is the SHA-256 of its bytes (first 12 hex chars); it lands in the audit trail and the cache key, so editing a file invalidates cached LLM answers.
- Lookup keys are character-unified and case-folded (`ي→ی`, `ك→ک`, ZWNJ→space, Persian digits→ASCII), so variants do not need every spelling.

Seed files here are **starter sets** grown from the Fanos dataset's most frequent values; they are expected to be replaced/extended with the real controlled vocabularies.
