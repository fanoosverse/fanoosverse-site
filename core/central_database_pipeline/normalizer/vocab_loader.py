"""
Module: /core/normalizer/vocab_loader.py
Description: Controlled-vocabulary CSV loading, indexing, and O(1) variant lookup.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

from normalizer.unify import unify_key

logger = logging.getLogger("fanoos.normalizer.vocab")


@dataclass(slots=True)
class VocabEntry:
    value: str
    category: str | None = None
    variants: tuple[str, ...] = ()


@dataclass(slots=True)
class Vocabulary:
    name: str
    version: str
    entries: list[VocabEntry]
    _exact: dict[str, VocabEntry] = field(default_factory=dict, init=False)
    _variant_owner: dict[str, tuple[VocabEntry, str]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for entry in self.entries:
            key = unify_key(entry.value)
            self._exact[key] = entry
            for variant in entry.variants:
                vkey = unify_key(variant)
                if vkey and vkey not in self._exact:
                    self._variant_owner.setdefault(vkey, (entry, variant))

    def resolve(self, raw: str) -> tuple[VocabEntry, str] | None:
        """Exact then variant lookup on the unified key."""
        key = unify_key(raw)
        if not key:
            return None
        exact = self._exact.get(key)
        if exact is not None:
            return exact, exact.value
        hit = self._variant_owner.get(key)
        if hit is not None:
            return hit[0], hit[1]
        return None

    def values(self) -> list[str]:
        return [entry.value for entry in self.entries]


def parse_vocab_csv(content: bytes | str, name: str) -> Vocabulary:
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    version = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    entries: list[VocabEntry] = []
    reader = csv.reader(io.StringIO(text))
    for row_no, row in enumerate(reader):
        if not row or all(not cell.strip() for cell in row):
            continue
        if row_no == 0 and row[0].strip().lower() == "value":
            continue
        value = row[0].strip()
        if not value:
            continue
        category = row[1].strip() if len(row) > 1 and row[1].strip() else None
        variants: tuple[str, ...] = ()
        if len(row) > 2 and row[2].strip():
            variants = tuple(v.strip() for v in row[2].split("|") if v.strip())
        entries.append(VocabEntry(value=value, category=category, variants=variants))
    return Vocabulary(name=name, version=version, entries=entries)


class VocabStore:
    """Loads all `*.csv` vocabularies in `/core/normalizer/vocab/` once."""

    def __init__(self, vocab_dir: Path | None = None) -> None:
        self.dir = vocab_dir or (Path(__file__).resolve().parent / "vocab")
        self._vocabs: dict[str, Vocabulary] = {}
        if self.dir.is_dir():
            for path in sorted(self.dir.glob("*.csv")):
                self._vocabs[path.stem] = parse_vocab_csv(path.read_bytes(), path.stem)

    def get(self, name: str) -> Vocabulary:
        return self._vocabs.get(name, Vocabulary(name=name, version="empty", entries=[]))