"""
Central LLM Configuration, Client Router, and Token Telemetry for Fanoos (/core).

Provides a unified, provider-agnostic interface (`call_llm`) and role-based configuration
profiles (`LLMProfile`) for all LLM-powered agents in the Fanoos pipeline (Extractor,
Normalizer, and Supervisor), strictly targeting GapGPT and AvalAI OpenAI-compatible endpoints.

Architecture & Inheritance:
    - EXTRACTOR  : Base profile loaded from `EXTRACTOR_*` (or legacy `LLM_*`) in `/core/.env`.
    - NORMALIZER : Inherits missing settings from `EXTRACTOR`; overrides via `NORMALIZER_*`.
    - SUPERVISOR : Inherits missing settings from `EXTRACTOR`; overrides via `SUPERVISOR_*`.
    * Security Rule: API keys are only inherited across profiles if `base_url` matches
      the base profile's provider URL, preventing cross-provider key leakage.

Environment Variables (`/core/.env`):
    # --- Shared / Extractor Defaults (GapGPT) ---
    EXTRACTOR_API_KEY=<gapgpt-api-key>
    EXTRACTOR_BASE_URL=https://api.gapgpt.app/v1
    EXTRACTOR_MODEL=gpt-4o
    EXTRACTOR_MAX_TOKENS=3500
    EXTRACTOR_MAX_TOKENS_PARAM=max_tokens          # or max_completion_tokens
    EXTRACTOR_TEMPERATURE=0.0                      # or "none" to omit parameter
    EXTRACTOR_STRUCTURED_MODE=json_schema          # "json_schema" or "json_object"
    EXTRACTOR_TIMEOUT=180

    # --- Normalizer Overrides (Optional) ---
    NORMALIZER_API_KEY=<api-key>        
    NORMALIZER_BASE_URL=https://api.gapgpt.app/v1
    NORMALIZER_MODEL=gpt-4o-mini
    NORMALIZER_STRUCTURED_MODE=json_object

    # --- Supervisor Overrides (AvalAI) ---
    SUPERVISOR_API_KEY=<avalai-api-key>
    SUPERVISOR_BASE_URL=https://api.avalai.ir/v1
    SUPERVISOR_MODEL=gemini-2.5-flash
    SUPERVISOR_STRUCTURED_MODE=json_object

Telemetry & Error Classification:
    - `USAGE` (collections.Counter): Tracks cumulative process-wide `input_tokens` and
      `output_tokens`, as well as per-role breakdowns (`<role>_input_tokens`, `<role>_output_tokens`).
    - `LLMError`: Categorizes failures into `kind="transient"` (network/rate-limit/5xx, safe to retry),
      `kind="fatal"` (HTTP 400/401/402/403/404, bad key or exhausted credit), and
      `kind="cut_off"` (`finish_reason == "length"`).

CLI Self-Test:
    Run `python llm_config.py` to verify connectivity and structured JSON output across active profiles.
"""

import json
import os
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Always load the central /core/.env file
CORE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=CORE_DIR / ".env", override=True)


@dataclass(frozen=True)
class LLMProfile:
    """Configuration profile for one agent role (extractor, normalizer, supervisor)."""
    name: str
    api_key: str
    base_url: str
    model: str
    max_tokens: int = 3500
    max_tokens_param: str = "max_tokens"
    temperature: float | None = 0.0
    structured_mode: str = "json_schema"  # "json_schema" or "json_object"
    timeout: float = 180.0
    extra_body: dict | None = None

    @classmethod
    def from_env(
        cls,
        prefix: str,
        name: str,
        base: "LLMProfile | None" = None,
        fallback_api_key: str = "",
    ) -> "LLMProfile":
        def get(key: str, default):
            val = (os.getenv(f"{prefix}_{key}") or "").strip()
            return val if val else default

        b = base
        temp = get("TEMPERATURE", None)
        extra = get("EXTRA_BODY", None)
        base_url = get("BASE_URL", b.base_url if b else "https://api.gapgpt.app/v1")
        inherited_key = b.api_key if (b and base_url == b.base_url) else ""

        return cls(
            name=name,
            api_key=get("API_KEY", fallback_api_key or inherited_key),
            base_url=base_url,
            model=get("MODEL", b.model if b else "gpt-4o"),
            max_tokens=int(get("MAX_TOKENS", b.max_tokens if b else 3500)),
            max_tokens_param=get("MAX_TOKENS_PARAM", b.max_tokens_param if b else "max_tokens"),
            temperature=(b.temperature if b else 0.0)
            if temp is None
            else (None if temp.lower() == "none" else float(temp)),
            structured_mode=get("STRUCTURED_MODE", b.structured_mode if b else "json_schema"),
            timeout=float(get("TIMEOUT", b.timeout if b else 180.0)),
            extra_body=(b.extra_body if b else None) if extra is None else json.loads(extra),
        )


# Profiles for all LLM-powered agents in /core
EXTRACTOR = LLMProfile.from_env(
    "EXTRACTOR",
    "extractor",
    fallback_api_key=(
        os.getenv("LLM_EXTRACTOR_GAPGPT")
        or os.getenv("LLM_EXTRACTOR_GAPGPT_1")
        or os.getenv("GAPGPT_API_KEY")
        or ""
    ).strip(),
)
NORMALIZER = LLMProfile.from_env("NORMALIZER", "normalizer", base=EXTRACTOR)
SUPERVISOR = LLMProfile.from_env(
    "SUPERVISOR",
    "supervisor",
    base=EXTRACTOR,
    fallback_api_key=(os.getenv("AVALAI_API_KEY") or "").strip(),
)

USAGE = Counter()
FATAL_STATUS = {400, 401, 402, 403, 404}


class LLMError(Exception):
    def __init__(self, message: str, kind: str = "transient") -> None:
        super().__init__(message)
        self.kind = kind


def _kind_of(error: Exception) -> str:
    return "fatal" if getattr(error, "status_code", None) in FATAL_STATUS else "transient"


@lru_cache(maxsize=None)
def _client(base_url: str, api_key: str, timeout: float) -> OpenAI:
    return OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=timeout,
        max_retries=0,
        default_headers={"Accept-Encoding": "gzip, deflate"},
    )


def call_llm(
    system_prompt: str,
    user_prompt: str,
    schema: dict | None = None,
    max_tokens: int | None = None,
    profile: LLMProfile = EXTRACTOR,
) -> str:
    p = profile
    if not p.api_key:
        raise LLMError(f"API key for profile '{p.name}' is missing in /core/.env", "fatal")

    kwargs = {
        "model": p.model,
        p.max_tokens_param: max_tokens or p.max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if p.temperature is not None:
        kwargs["temperature"] = p.temperature
    if p.extra_body:
        kwargs["extra_body"] = p.extra_body

    if schema:
        if p.structured_mode == "json_schema":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "strict": True, "schema": schema},
            }
        elif p.structured_mode == "json_object":
            kwargs["messages"][0]["content"] += (
                "\n\nReturn ONE JSON object that follows this JSON Schema exactly:\n"
                + json.dumps(schema, ensure_ascii=False)
            )
            kwargs["response_format"] = {"type": "json_object"}
        else:
            raise LLMError(f"Unknown structured_mode for '{p.name}': {p.structured_mode}", "fatal")

    try:
        resp = _client(p.base_url, p.api_key, p.timeout).chat.completions.create(**kwargs)
    except Exception as e:
        raise LLMError(f"LLM call failed ({p.name}/{p.model}): {type(e).__name__}: {e}", _kind_of(e)) from e

    if resp.usage:
        used_in, used_out = resp.usage.prompt_tokens or 0, resp.usage.completion_tokens or 0
        USAGE["input_tokens"] += used_in
        USAGE["output_tokens"] += used_out
        USAGE[f"{p.name}_input_tokens"] += used_in
        USAGE[f"{p.name}_output_tokens"] += used_out

    choice = resp.choices[0]
    if choice.finish_reason == "length":
        raise LLMError("Output was cut off.", "cut_off")
    if not choice.message.content:
        raise LLMError("LLM returned an empty reply.", "transient")
    return choice.message.content