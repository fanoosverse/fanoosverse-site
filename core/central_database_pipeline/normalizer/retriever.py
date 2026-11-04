"""
Module: /core/normalizer/retriever.py
Description: Character-trigram Jaccard similarity retriever for ranking CSV vocabulary candidates.
"""
from __future__ import annotations

from dataclasses import dataclass
from normalizer.unify import unify_key
from normalizer.vocab_loader import VocabEntry, Vocabulary


@dataclass(slots=True)
class TrigramRetriever:
    min_score: float = 0.08

    @staticmethod
    def _trigrams(key: str) -> set[str]:
        padded = f"  {key} "
        return {padded[i : i + 3] for i in range(max(1, len(padded) - 2))}

    def score(self, a: str, b: str) -> float:
        ka, kb = unify_key(a), unify_key(b)
        if not ka or not kb:
            return 0.0
        ga, gb = self._trigrams(ka), self._trigrams(kb)
        if not ga or not gb:
            return 0.0
        return len(ga & gb) / len(ga | gb)

    def retrieve_candidates(self, vocab: Vocabulary, raw_value: str, top_k: int = 8) -> list[str]:
        """Returns the top_k canonical values from `vocab` closest to `raw_value`."""
        scored: list[tuple[VocabEntry, float]] = []
        query = unify_key(raw_value)
        for entry in vocab.entries:
            best = self.score(query, unify_key(entry.value))
            for variant in entry.variants:
                best = max(best, self.score(query, unify_key(variant)))
            if best >= self.min_score:
                scored.append((entry, best))
        scored.sort(key=lambda pair: (-pair[1], pair[0].value))
        return [entry.value for entry, _ in scored[:top_k]]