"""
LLM settings and the one function that talks to the LLM.

Change provider or model: edit .env. Nothing else needs to change.
Test the connection: python llm_config.py

.env:
    LLM_EXTRACTOR_GAPGPT=<api key>                (LLM_EXTRACTOR also works)
    LLM_BASE_URL=https://api.gapgpt.app/v1        (default)
    LLM_MODEL=gpt-4o                              (default)
Optional:
    LLM_MAX_TOKENS=3500
    LLM_MAX_TOKENS_PARAM=max_tokens               (or max_completion_tokens)
    LLM_TEMPERATURE=0                             ("none" means do not send it)
    LLM_STRUCTURED_MODE=json_schema               (or json_object)
    LLM_TIMEOUT=180                               (seconds)
    LLM_EXTRA_BODY={"provider":{"require_parameters":true}}
"""
import json
import os
import sys
from collections import Counter

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

API_KEY = (os.getenv("LLM_EXTRACTOR_GAPGPT") or os.getenv("LLM_EXTRACTOR") or "").strip()
BASE_URL = os.getenv("LLM_BASE_URL", "https://api.gapgpt.app/v1").strip()
MODEL = os.getenv("LLM_MODEL", "gpt-4o").strip()
MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "3500"))
MAX_TOKENS_PARAM = os.getenv("LLM_MAX_TOKENS_PARAM", "max_tokens")
_temp = os.getenv("LLM_TEMPERATURE", "0")
TEMPERATURE = None if _temp.lower() == "none" else float(_temp)
STRUCTURED_MODE = os.getenv("LLM_STRUCTURED_MODE", "json_schema")
TIMEOUT = float(os.getenv("LLM_TIMEOUT", "180"))
EXTRA_BODY = json.loads(os.getenv("LLM_EXTRA_BODY") or "null")

# Token use of all calls in this process. The pipeline reads it for cost control.
USAGE = Counter()

FATAL_STATUS = {400, 401, 402, 403, 404}


class LLMError(Exception):
    """
    Any LLM failure.
    kind = "transient" : network, rate limit or server error. Retry later.
    kind = "fatal"     : bad key, no credit or bad request. Retry will not help.
    kind = "cut_off"   : the answer hit the output limit.
    """

    def __init__(self, message: str, kind: str = "transient") -> None:
        super().__init__(message)
        self.kind = kind


def _kind_of(error: Exception) -> str:
    return "fatal" if getattr(error, "status_code", None) in FATAL_STATUS else "transient"


def call_llm(system_prompt: str, user_prompt: str, schema: dict | None = None,
             max_tokens: int | None = None) -> str:
    """Send a prompt and return the reply text. With a schema, the reply is JSON text."""
    if not API_KEY:
        raise LLMError("API key is not set. Put LLM_EXTRACTOR_GAPGPT in your .env file.", "fatal")

    kwargs = {
        "model": MODEL,
        MAX_TOKENS_PARAM: max_tokens or MAX_TOKENS,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if TEMPERATURE is not None:
        kwargs["temperature"] = TEMPERATURE
    if EXTRA_BODY:
        kwargs["extra_body"] = EXTRA_BODY

    if schema:
        if STRUCTURED_MODE == "json_schema":
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "output", "strict": True, "schema": schema},
            }
        elif STRUCTURED_MODE == "json_object":  # the schema goes into the prompt
            kwargs["messages"][0]["content"] += (
                "\n\nReturn ONE JSON object that follows this JSON Schema exactly:\n"
                + json.dumps(schema, ensure_ascii=False)
            )
            kwargs["response_format"] = {"type": "json_object"}
        else:
            raise LLMError(f"Unknown LLM_STRUCTURED_MODE: {STRUCTURED_MODE}", "fatal")

    try:
        client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=TIMEOUT, max_retries=0)
        resp = client.chat.completions.create(**kwargs)
    except Exception as e:
        raise LLMError(f"LLM call failed ({MODEL}): {type(e).__name__}: {e}", _kind_of(e)) from e

    if resp.usage:
        USAGE["input_tokens"] += resp.usage.prompt_tokens or 0
        USAGE["output_tokens"] += resp.usage.completion_tokens or 0

    choice = resp.choices[0]
    if choice.finish_reason == "length":
        raise LLMError("Output was cut off.", "cut_off")
    if not choice.message.content:
        raise LLMError("LLM returned an empty reply.", "transient")
    return choice.message.content


if __name__ == "__main__":  # connection self-test
    from pydantic import BaseModel, ConfigDict

    class Mini(BaseModel):
        model_config = ConfigDict(extra="forbid")
        role_title: str
        seniority: list[str]
        salary_min: int | None

    print(f"endpoint={BASE_URL}  model={MODEL}  mode={STRUCTURED_MODE}")
    ok = 0
    try:
        print("1 ping      :", call_llm("You are a test.", "Reply with exactly: OK", max_tokens=20))
        ok += 1
    except LLMError as e:
        print("1 FAILED    :", e)
    try:
        raw = call_llm("Extract the job info. Use null or [] if not in the text.",
                       "مهندس ارشد یادگیری ماشین، تهران، حقوق ۸۰ میلیون تومان",
                       Mini.model_json_schema())
        print("2 structured:", Mini.model_validate_json(raw).model_dump())
        ok += 1
    except Exception as e:
        print("2 FAILED    :", str(e)[:400])
        print("  hint: set LLM_STRUCTURED_MODE=json_object in .env and retry")
    print(f"Passed {ok} of 2")
    sys.exit(0 if ok == 2 else 1)
