"""
Module: /core/normalizer/normalizer_agent.py
Description: Clean 3-Stage Normalizer Agent (Deterministic CSV Lookup -> Trigram + LLM -> Assembly).
Replaces the legacy 88-file normalizer while preserving full use of `vocab/*.csv` and `TrigramRetriever`.
"""
from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from llm_config import LLMError, NORMALIZER, call_llm
from normalizer.retriever import TrigramRetriever
from normalizer.unify import is_placeholder, strip_version_and_parens, unify_key
from normalizer.vocab_loader import VocabStore
from schema import JobAd

logger = logging.getLogger("fanoos.normalizer")

# Maps each JobAd field to its corresponding CSV file in /core/normalizer/vocab/<name>.csv
FIELD_TO_VOCAB: dict[str, str] = {
    "organization": "organization",
    "role_normalized": "role",
    "domain": "domain",
    "industry": "industry",
    "compensation_type": "compensation_type",
    "location": "location",
    "seniority": "seniority",
    "skills_required": "capability",
    "skills_preferred": "capability",
    "ai_skills": "capability",
    "tools": "capability",
    "soft_skills": "capability",
    "benefits": "benefit",
    "education": "education",
    "education_field": "education_field",
    "language": "language",
}

SCALAR_VOCAB_FIELDS = (
    "organization",
    "role_normalized",
    "domain",
    "industry",
    "compensation_type",
    "location",
)

LIST_VOCAB_FIELDS = (
    "seniority",
    "skills_required",
    "skills_preferred",
    "ai_skills",
    "tools",
    "soft_skills",
    "benefits",
    "education",
    "education_field",
    "language",
)

SKILL_FIELDS = {"skills_required", "skills_preferred", "ai_skills", "tools"}


class LLMResolvedBatch(BaseModel):
    """Schema for LLM resolution of items that missed deterministic CSV lookup."""
    model_config = ConfigDict(extra="forbid")

    organization: str | None
    role_normalized: str
    domain: str
    industry: str | None
    compensation_type: str | None
    location: str | None
    seniority: list[str]
    skills_required: list[str]
    skills_preferred: list[str]
    ai_skills: list[str]
    tools: list[str]
    soft_skills: list[str]
    benefits: list[str]
    education: list[str]
    education_field: list[str]
    language: list[str]


LLM_BATCH_SCHEMA = LLMResolvedBatch.model_json_schema()


@lru_cache(maxsize=1)
def get_vocab_store() -> VocabStore:
    vocab_dir = Path(__file__).resolve().parent / "vocab"
    return VocabStore(vocab_dir)


def _dedup_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned or is_placeholder(cleaned):
            continue
        k = unify_key(cleaned)
        if k not in seen:
            seen.add(k)
            out.append(cleaned)
    return out


def _resolve_token_deterministically(
    raw_val: str,
    vocab_name: str,
    store: VocabStore,
    retriever: TrigramRetriever,
) -> tuple[str | None, list[str]]:
    """
    Tries O(1) exact/variant CSV lookup first (before and after stripping version/parens).
    Returns:
        (canonical_value_if_found_or_None, top_trigram_candidates_if_unresolved)
    """
    if not raw_val or is_placeholder(raw_val):
        return None, []

    vocab = store.get(vocab_name)
    hit = vocab.resolve(raw_val)
    if hit is not None:
        return hit[0].value, []

    base, _removed = strip_version_and_parens(raw_val)
    if base and base != raw_val:
        hit = vocab.resolve(base)
        if hit is not None:
            return hit[0].value, []

    candidates = retriever.retrieve_candidates(vocab, base or raw_val, top_k=8)
    return None, candidates


def normalize_single_ad(
    extracted_ad: JobAd,
    previous_normalized: JobAd | None = None,
    rejection_criteria: list[str] | None = None,
    llm_retries: int = 3,
) -> tuple[JobAd | None, list[str]]:
    """
    Normalizes an extracted `JobAd` using:
      1. Deterministic CSV lookup (`/core/normalizer/vocab/*.csv`)
      2. Trigram candidate retrieval + `/core/llm_config.py` (`NORMALIZER` profile) for unresolved items
         or Supervisor rejection criteria repair.
    """
    store = get_vocab_store()
    retriever = TrigramRetriever()
    source_ad = previous_normalized or extracted_ad
    data = source_ad.model_dump(mode="json")

    unresolved_report: dict[str, Any] = {}
    resolved_state: dict[str, Any] = {}
    new_skill_candidates: list[str] = list(data.get("candidate_new_skill") or [])

    # -----------------------------------------------------------------
    # STAGE 1: Deterministic CSV Lookup (0 Tokens)
    # -----------------------------------------------------------------
    for field_name in SCALAR_VOCAB_FIELDS:
        raw_val = data.get(field_name)
        vocab_name = FIELD_TO_VOCAB[field_name]
        if not raw_val or not isinstance(raw_val, str) or is_placeholder(raw_val):
            resolved_state[field_name] = None
            continue

        canonical, candidates = _resolve_token_deterministically(raw_val, vocab_name, store, retriever)
        if canonical is not None:
            resolved_state[field_name] = canonical
        else:
            # Keep original value as draft and flag for LLM with CSV trigram candidates
            resolved_state[field_name] = raw_val.strip()
            unresolved_report[field_name] = {
                "raw": raw_val,
                "csv_candidates": candidates,
            }

    for field_name in LIST_VOCAB_FIELDS:
        raw_list = data.get(field_name) or []
        vocab_name = FIELD_TO_VOCAB[field_name]
        field_resolved: list[str] = []
        field_unresolved: list[dict[str, Any]] = []

        for raw_item in raw_list:
            if not isinstance(raw_item, str) or is_placeholder(raw_item):
                continue
            canonical, candidates = _resolve_token_deterministically(raw_item, vocab_name, store, retriever)
            if canonical is not None:
                field_resolved.append(canonical)
            else:
                base, _ = strip_version_and_parens(raw_item)
                field_resolved.append(base or raw_item.strip())
                field_unresolved.append({"raw": raw_item, "csv_candidates": candidates})

        resolved_state[field_name] = _dedup_preserve_order(field_resolved)
        if field_unresolved:
            unresolved_report[field_name] = field_unresolved

    # -----------------------------------------------------------------
    # STAGE 2: LLM Resolution (Only if unresolved items exist OR Supervisor rejected)
    # -----------------------------------------------------------------
    needs_llm = bool(unresolved_report) or bool(rejection_criteria)

    if needs_llm:
        system_prompt = (
            "You are the Fanoos Canonical Normalizer Agent.\n"
            "You receive a job advertisement's partially normalized fields, along with `Unresolved Items & CSV Candidates` "
            "and optional `Supervisor Rejection Criteria`.\n\n"
            "Rules:\n"
            "1. Keep already-canonical English values intact unless Supervisor Rejection Criteria ask to change them.\n"
            "2. For each unresolved item, if one of its `csv_candidates` matches the meaning of `raw`, select that exact candidate string.\n"
            "3. If no candidate in `csv_candidates` matches, translate/clean the term into standard English Title Case "
            "(e.g., 'مهندس ماشین لرنینگ' -> 'Machine Learning Engineer', 'تهران' -> 'Tehran'). Strip version numbers.\n"
            "4. `role_normalized` and `domain` MUST be non-empty English strings.\n"
            "5. `seniority` values must be lowercase (e.g., 'intern', 'junior', 'mid', 'senior', 'lead', 'manager').\n"
            "6. Every item in `ai_skills` must also appear in `skills_required` or `skills_preferred` with identical spelling.\n"
            "7. If Supervisor Rejection Criteria are provided, strictly apply those fixes."
        )

        user_parts = [
            f"Original Persian Role Title: {extracted_ad.role_title}",
            f"Current Field Values:\n{json.dumps(resolved_state, ensure_ascii=False, indent=2)}",
        ]
        if unresolved_report:
            user_parts.append(
                f"Unresolved Items & Closest CSV Vocabulary Candidates:\n"
                f"{json.dumps(unresolved_report, ensure_ascii=False, indent=2)}"
            )
        if rejection_criteria:
            user_parts.append(
                "Supervisor Rejection Criteria to Fix:\n"
                + "\n".join(f"- {c}" for c in rejection_criteria)
            )

        user_prompt = "\n\n".join(user_parts)

        raw_reply = ""
        for attempt in range(1, llm_retries + 1):
            try:
                raw_reply = call_llm(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    schema=LLM_BATCH_SCHEMA,
                    max_tokens=2200,
                    profile=NORMALIZER,
                )
                break
            except LLMError as e:
                if e.kind == "fatal":
                    raise
                logger.warning("Normalizer LLM transient error (try %d/%d): %s", attempt, llm_retries, e)
                if attempt < llm_retries:
                    time.sleep(2 ** attempt)
                else:
                    raise

        try:
            llm_cleaned = LLMResolvedBatch.model_validate_json(raw_reply).model_dump()
            resolved_state.update(llm_cleaned)
        except ValidationError as ve:
            return None, [f"Normalizer LLM output failed schema validation: {ve}"]

    # -----------------------------------------------------------------
    # STAGE 3: Post-Hygiene, `candidate_new_skill` Tagging & Assembly
    # -----------------------------------------------------------------
    if not (resolved_state.get("role_normalized") or "").strip():
        resolved_state["role_normalized"] = extracted_ad.role_normalized
    if not (resolved_state.get("domain") or "").strip():
        resolved_state["domain"] = extracted_ad.domain

    cap_vocab = store.get("capability")
    for lf in LIST_VOCAB_FIELDS:
        items = _dedup_preserve_order(resolved_state.get(lf) or [])
        if lf == "seniority":
            items = [i.lower() for i in items]
        resolved_state[lf] = items

        # Any skill not yet in capability.csv is recorded in `candidate_new_skill` (without dropping the ad!)
        if lf in SKILL_FIELDS and len(cap_vocab.values()) > 0:
            for skill_str in items:
                if cap_vocab.resolve(skill_str) is None:
                    new_skill_candidates.append(skill_str)

    # Enforce `ai_skills` subset rule
    req_and_pref = {
        unify_key(s): s
        for s in (resolved_state["skills_required"] + resolved_state["skills_preferred"])
    }
    aligned_ai: list[str] = []
    for ai_item in resolved_state["ai_skills"]:
        k = unify_key(ai_item)
        if k in req_and_pref:
            aligned_ai.append(req_and_pref[k])
        else:
            resolved_state["skills_required"].append(ai_item)
            aligned_ai.append(ai_item)
    resolved_state["ai_skills"] = _dedup_preserve_order(aligned_ai)

    # Salary currency consistency check
    if data.get("salary_min") is None and data.get("salary_max") is None:
        data["salary_currency"] = None

    final_dict = {
        **data,
        **resolved_state,
        "candidate_new_skill": _dedup_preserve_order(new_skill_candidates),
    }

    try:
        validated_job_ad = JobAd.model_validate(final_dict)
        return validated_job_ad, []
    except ValidationError as ve:
        return None, [f"Final JobAd validation error after normalization: {ve}"]