"""
Module: extractor/extractor_agent.py
Author: Adapted from Mani Yahyazadeh's extraction pipeline for single-ad execution.
Description: Extracts a single `RawJobAd` into a validated `JobAd` Pydantic model,
supporting iterative repair loops driven by Supervisor rejection criteria.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import date
from typing import Any

from pydantic import ConfigDict, ValidationError, create_model

from llm_config import EXTRACTOR, LLMError, call_llm
from prompt_manager import get_prompt
from schema import JobAd, PIPELINE_METADATA_FIELDS, SourceType

logger = logging.getLogger("fanoos.extractor")

# LLM fills only the 30 semantic fields; Python injects the 7 provenance metadata fields
_llm_fields = {
    name: (field_info.annotation, ...)
    for name, field_info in JobAd.model_fields.items()
    if name not in PIPELINE_METADATA_FIELDS
}
SemanticJobAd = create_model(
    "SemanticJobAd",
    __config__=ConfigDict(extra="forbid"),
    **_llm_fields,
)
EXTRACTOR_JSON_SCHEMA = SemanticJobAd.model_json_schema()


def compute_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_enriched_ad_text(raw_ad: Any) -> str:
    """Prepends scraped title, company, and location to raw_text if not already present."""
    if isinstance(raw_ad, dict):
        title = raw_ad.get("raw_title") or ""
        company = raw_ad.get("raw_company") or ""
        location = raw_ad.get("raw_location") or ""
        body = raw_ad.get("raw_text") or raw_ad.get("text") or ""
    else:
        title = getattr(raw_ad, "raw_title", "") or ""
        company = getattr(raw_ad, "raw_company", "") or ""
        location = getattr(raw_ad, "raw_location", "") or ""
        body = getattr(raw_ad, "raw_text", "") or getattr(raw_ad, "text", "")

    header_lines = []
    if title and title not in body[:200]:
        header_lines.append(f"عنوان شغلی (Job Title): {title}")
    if company and company not in body[:300]:
        header_lines.append(f"شرکت (Organization): {company}")
    if location and location not in body[:300]:
        header_lines.append(f"محل کار (Location): {location}")

    if header_lines:
        return "\n".join(header_lines) + "\n\n" + body.strip()
    return body.strip()


def check_deterministic_rules(job: JobAd) -> list[str]:
    """Cross-field logical checks from Mani's `rule_problems`."""
    problems: list[str] = []
    if job.salary_min is not None and job.salary_max is not None and job.salary_min > job.salary_max:
        problems.append("salary_min is bigger than salary_max")
    if job.age_min is not None and job.age_max is not None and job.age_min > job.age_max:
        problems.append("age_min is bigger than age_max")
    if (
        job.company_size_min is not None
        and job.company_size_max is not None
        and job.company_size_min > job.company_size_max
    ):
        problems.append("company_size_min is bigger than company_size_max")

    for name in (
        "experience_years_min",
        "salary_min",
        "salary_max",
        "age_min",
        "age_max",
        "company_size_min",
        "company_size_max",
        "internship_duration_months",
    ):
        value = getattr(job, name)
        if value is not None and value < 0:
            problems.append(f"{name} is negative")

    if not job.role_title.strip() or not job.role_normalized.strip():
        problems.append("role_title and role_normalized must not be empty")
    if not job.domain.strip():
        problems.append("domain must not be empty")
    if not job.work_mode:
        problems.append('work_mode must not be empty, use ["unknown"]')
    return problems


def _describe_validation_error(error: ValidationError) -> list[str]:
    items = []
    for err in error.errors()[:10]:
        where = ".".join(str(p) for p in err["loc"]) or "item"
        items.append(f"{where}: {err['msg']}")
    return items


def extract_single_ad(
    document_id: str,
    collector: str,
    collected_at: date,
    ad_text: str,
    version: str = "v2",
    previous_attempt: dict | None = None,
    rejection_criteria: list[str] | None = None,
    llm_retries: int = 3,
) -> tuple[JobAd | None, dict | None, list[str]]:
    """
    Extracts structured fields for one single job ad.
    Returns (validated_JobAd_or_None, raw_llm_dict_or_None, list_of_problems).
    """
    system_prompt = get_prompt("extractor.main")

    parts = [f"Posting id: {document_id}\n<<<\n{ad_text}\n>>>"]
    if previous_attempt:
        parts.append(
            "Your previous answer for this posting:\n"
            + json.dumps(previous_attempt, ensure_ascii=False, indent=2)
        )
    if rejection_criteria:
        parts.append(
            "Problems / Supervisor Criteria to fix (keep all other valid fields intact):\n"
            + "\n".join(f"- {p}" for p in rejection_criteria)
        )

    user_prompt = "\n\n".join(parts)

    raw_reply = ""
    for attempt in range(1, llm_retries + 1):
        try:
            raw_reply = call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=EXTRACTOR_JSON_SCHEMA,
                max_tokens=2500,
                profile=EXTRACTOR,
            )
            break
        except LLMError as e:
            if e.kind == "fatal":
                raise
            if e.kind == "cut_off":
                return None, previous_attempt, ["The model output was cut off. Make evidence_notes shorter."]
            logger.warning("Extractor LLM transient error (try %d/%d): %s", attempt, llm_retries, e)
            if attempt < llm_retries:
                time.sleep(2 ** attempt)
            else:
                raise

    try:
        parsed_dict = json.loads(raw_reply)
        if not isinstance(parsed_dict, dict):
            return None, None, ["Extractor reply is not a JSON object."]
    except json.JSONDecodeError as je:
        return None, None, [f"Invalid JSON from Extractor: {je}"]

    try:
        extracted_semantic = SemanticJobAd.model_validate(parsed_dict)
        job = JobAd.model_validate(
            {
                **extracted_semantic.model_dump(),
                "document_id": document_id,
                "collector": collector,
                "source_type": SourceType.JOB_POSTING,
                "collected_at": collected_at,
                "text": ad_text,
                "content_hash": compute_content_hash(ad_text),
                "version": version,
            }
        )
    except ValidationError as ve:
        return None, parsed_dict, _describe_validation_error(ve)

    problems = check_deterministic_rules(job)
    if problems:
        return None, parsed_dict, problems

    return job, parsed_dict, []