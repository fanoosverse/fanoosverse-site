# -*- coding: utf-8 -*-
"""
llm_client.py: send a request to any model with one simple function

    from llm_client import ask
    r = ask("nemotron-3-ultra", "Hello! Introduce yourself in one sentence.")
    print(r["status"], r["seconds"], r["text"])

The output is always a dictionary: {"model", "status", "seconds", "text"}
A status of "ok" means success; otherwise the cause of the error is in that same field.
"""
import time
import requests

from llm_config import MODELS, PROVIDERS, get_key

TIMEOUT = 180        # seconds
MAX_TOKENS = 3000    # reasoning models spend part of the tokens on thinking


def ask(model_key, prompt, max_tokens=MAX_TOKENS, retries=2):
    m = MODELS[model_key]
    prov = PROVIDERS[m["provider"]]
    key, err = get_key(m["provider"])
    out = {"model": m["name"], "status": "", "seconds": 0.0, "text": ""}
    if err:
        out["status"] = f"NO_KEY: {err}"
        return out

    url = prov["base"] + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {"model": m["id"], "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}

    r = None
    for attempt in range(max(1, retries)):
        t0 = time.time()
        try:
            r = requests.post(url, headers=headers, json=body, timeout=TIMEOUT)
        except requests.RequestException as e:
            out.update(status=f"NETWORK: {type(e).__name__}", seconds=round(time.time() - t0, 2))
            if attempt < retries - 1:
                time.sleep(5)       # network errors are usually temporary: try once more
                continue
            return out
        out["seconds"] = round(time.time() - t0, 2)
        if r.status_code in (429, 500, 502, 503) and attempt < retries - 1:
            time.sleep(20)          # temporary error or rate limit: wait and retry once
            continue
        break

    if r.status_code != 200:
        hint = ""
        if r.status_code == 403:
            hint = " (usually the IP/region is blocked; try a system-wide VPN)"
        elif r.status_code == 404:
            hint = " (the model ID is wrong; run list_models)"
        out["status"] = f"HTTP {r.status_code}{hint}: {r.text[:200]}"
        return out
    try:
        data = r.json()
        out["text"] = (data["choices"][0]["message"].get("content") or "").strip()
    except (ValueError, KeyError, IndexError, TypeError):
        out["status"] = f"BAD_RESPONSE: {r.text[:200]}"
        return out
    out["status"] = "ok" if out["text"] else "EMPTY (increase MAX_TOKENS)"
    return out


def list_models(provider):
    """Returns the IDs of all models available on a service (to find the correct ID)."""
    key, err = get_key(provider)
    if err:
        raise RuntimeError(err)
    r = requests.get(PROVIDERS[provider]["base"] + "/models",
                     headers={"Authorization": f"Bearer {key}"}, timeout=60)
    r.raise_for_status()
    return [d["id"].replace("models/", "") for d in r.json().get("data", [])]
