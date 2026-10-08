# -*- coding: utf-8 -*-
"""
llm_config.py: connection configuration for the selected models

All services use the OpenAI format (/chat/completions), so only the base URL,
the key variable name and the model ID differ.

Status of each model, based on real tests up to 2026-10-08:
  tested        tested in practice
  untested      not tested (no key/access); the model ID may need correction
  not_free_now  no longer has a free (:free) version on OpenRouter
"""
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent

PROVIDERS = {
    "google":     {"env": "GOOGLE_API_KEY",     "base": "https://generativelanguage.googleapis.com/v1beta/openai", "delay": 7},
    "groq":       {"env": "GROQ_API_KEY",       "base": "https://api.groq.com/openai/v1",                          "delay": 3},
    "mistral":    {"env": "MISTRAL_API_KEY",    "base": "https://api.mistral.ai/v1",                               "delay": 3},
    "openrouter": {"env": "OPENROUTER_API_KEY", "base": "https://openrouter.ai/api/v1",                            "delay": 4},
    "nvidia":     {"env": "NVIDIA_API_KEY",     "base": "https://integrate.api.nvidia.com/v1",                     "delay": 3},
}

MODELS = {
    "nemotron-3-ultra": {
        "name": "Nemotron 3 Ultra", "company": "NVIDIA", "provider": "openrouter",
        "id": "nvidia/nemotron-3-ultra-550b-a55b:free", "context": 1_000_000,
        "category": "Reasoning / agentic", "status": "tested",
    },
    "gemini-flash": {
        "name": "Gemini Flash", "company": "Google", "provider": "google",
        "id": "gemini-flash-latest", "context": 1_000_000,
        "category": "General / multimodal", "status": "untested",
    },
    "llama-3.3-70b": {
        "name": "Llama 3.3 70B", "company": "Meta", "provider": "groq",
        "id": "llama-3.3-70b-versatile", "context": 128_000,
        "category": "General (fast)", "status": "untested",
    },
    "devstral": {
        "name": "Devstral", "company": "Mistral", "provider": "mistral",
        "id": "devstral-small-latest", "context": 256_000,
        "category": "Coding", "status": "untested",
    },
    "kimi-k2.6": {
        "name": "Kimi K2.6", "company": "Moonshot AI", "provider": "nvidia",
        "id": "moonshotai/kimi-k2.6", "context": 256_000,
        "category": "Agentic coding", "status": "untested",
    },
    "deepseek-v4-flash": {
        "name": "DeepSeek V4 Flash", "company": "DeepSeek", "provider": "openrouter",
        "id": "deepseek/deepseek-v4-flash:free", "context": 1_000_000,
        "category": "Reasoning / coding", "status": "not_free_now",
    },
    "qwen-3.6-plus": {
        "name": "Qwen 3.6 Plus Preview", "company": "Alibaba", "provider": "openrouter",
        "id": "qwen/qwen3.6-plus-preview:free", "context": 1_000_000,
        "category": "General / coding", "status": "not_free_now",
    },
}


def load_dotenv(path=None):
    """Loads variables from the .env file (next to this file) into os.environ."""
    p = Path(path) if path else HERE / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def get_key(provider):
    """Returns (key, error). If the key is missing or a placeholder, error is set."""
    load_dotenv()
    env = PROVIDERS[provider]["env"]
    key = os.environ.get(env, "").strip().strip('"').strip("'")
    if not key:
        return None, f"{env} key is not set (see the .env file)"
    if not key.isascii() or " " in key or key.upper().startswith(("YOUR", "PASTE")):
        return None, f"{env} key is not real (placeholder text or contains spaces)"
    return key, None
