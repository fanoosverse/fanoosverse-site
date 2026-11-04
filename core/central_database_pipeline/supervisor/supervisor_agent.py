"""
Module: supervisor/supervisor_agent.py
Author: Ahmadreza Hashemi
Description: Dual-stage AI + optional Human Supervisor Agent.
  - Stage 1 (`supervise_extraction`)   : Checks Extractor output against raw Persian job text.
  - Stage 2 (`supervise_normalization`): Checks Normalizer output against Extracted JobAd.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pydantic import ValidationError

from llm_config import LLMError, SUPERVISOR, call_llm
from prompt_manager import get_prompt
from schema import JobAd, PIPELINE_METADATA_FIELDS, SupervisorDecision

logger = logging.getLogger("fanoos.supervisor")

MAX_SUPERVISOR_ATTEMPTS = 3


def _requires_human_supervision(record_dict: dict, stage: str) -> SupervisorDecision:
    """Interactive CLI human gate (only active if SUPERVISOR_HUMAN_REVIEW=true in .env)."""
    print("\n" + "=" * 60)
    print(f" 🛑 PENDING HUMAN APPROVAL ({stage.upper()}) 🛑 ")
    print("=" * 60)
    print(f"Document ID : {record_dict.get('document_id', 'N/A')}")
    print(f"Role Title  : {record_dict.get('role_title', 'N/A')}")
    print(f"Role Norm.  : {record_dict.get('role_normalized', 'N/A')}")
    print(f"Organization: {record_dict.get('organization', 'N/A')}")
    print("-" * 60)

    user_input = input("Type 'Y' to approve, or type rejection criteria: ").strip()
    if user_input.upper() == "Y":
        return SupervisorDecision(is_approved=True, rejection_reason="")
    return SupervisorDecision(is_approved=False, rejection_reason=f"Human Supervisor: {user_input}")


def _call_supervisor_llm(system_prompt: str, user_message: str) -> SupervisorDecision:
    last_err = ""
    schema = SupervisorDecision.model_json_schema()

    for attempt in range(1, MAX_SUPERVISOR_ATTEMPTS + 1):
        try:
            raw = call_llm(
                system_prompt=system_prompt,
                user_prompt=user_message,
                schema=schema,
                max_tokens=1500,
                profile=SUPERVISOR,
            )
            return SupervisorDecision.model_validate_json(raw)
        except ValidationError as ve:
            last_err = f"Malformed supervisor JSON: {str(ve)[:200]}"
        except LLMError as le:
            if le.kind != "transient":
                raise
            last_err = str(le)

        if attempt < MAX_SUPERVISOR_ATTEMPTS:
            time.sleep(2 ** attempt)

    raise LLMError(f"Supervisor unavailable after {MAX_SUPERVISOR_ATTEMPTS} tries: {last_err}", "fatal")


def supervise_extraction(job_ad: JobAd, raw_text: str) -> SupervisorDecision:
    """Stage 1: Validates Extractor output against raw Persian job ad text."""
    system_prompt = get_prompt("supervisor.extractor")
    semantic_fields = job_ad.model_dump(mode="json", exclude=PIPELINE_METADATA_FIELDS)

    user_message = (
        f"Initial Data (Raw Text):\n{raw_text}\n\n"
        f"Completed Fields (Parsed JSON):\n{json.dumps(semantic_fields, ensure_ascii=False, indent=2)}"
    )

    decision = _call_supervisor_llm(system_prompt, user_message)
    if not decision.is_approved:
        logger.info("Stage-1 Supervisor REJECTED %s: %s", job_ad.document_id, decision.rejection_reason)
        return decision

    if os.getenv("SUPERVISOR_HUMAN_REVIEW", "false").lower() == "true":
        return _requires_human_supervision(job_ad.model_dump(mode="json"), stage="extraction")

    logger.info("Stage-1 Supervisor APPROVED extraction for %s.", job_ad.document_id)
    return decision


def supervise_normalization(extracted_ad: JobAd, normalized_ad: JobAd) -> SupervisorDecision:
    """Stage 2: Validates Normalizer output against Stage-1 approved Extracted JobAd."""
    system_prompt = get_prompt("supervisor.normalizer")
    before_fields = extracted_ad.model_dump(mode="json", exclude=PIPELINE_METADATA_FIELDS)
    after_fields = normalized_ad.model_dump(mode="json", exclude=PIPELINE_METADATA_FIELDS)

    user_message = (
        f"Extracted Record (Before Normalization):\n"
        f"{json.dumps(before_fields, ensure_ascii=False, indent=2)}\n\n"
        f"Normalized Record (After Normalization):\n"
        f"{json.dumps(after_fields, ensure_ascii=False, indent=2)}"
    )

    decision = _call_supervisor_llm(system_prompt, user_message)
    if not decision.is_approved:
        logger.info("Stage-2 Supervisor REJECTED %s: %s", normalized_ad.document_id, decision.rejection_reason)
        return decision

    if os.getenv("SUPERVISOR_HUMAN_REVIEW", "false").lower() == "true":
        return _requires_human_supervision(normalized_ad.model_dump(mode="json"), stage="normalization")

    logger.info("Stage-2 Supervisor APPROVED normalization for %s.", normalized_ad.document_id)
    return decision