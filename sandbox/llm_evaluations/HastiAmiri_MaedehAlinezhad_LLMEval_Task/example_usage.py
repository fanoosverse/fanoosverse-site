# -*- coding: utf-8 -*-
"""
example_usage.py: usage example

    python example_usage.py                 # one model (default: nemotron-3-ultra)
    python example_usage.py devstral        # any model of your choice
    python example_usage.py --all           # all models whose keys are configured
"""
import sys
import time

from llm_config import MODELS, PROVIDERS
from llm_client import ask

PROMPT = "Write a Python function that checks whether a number is prime."


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "nemotron-3-ultra"
    keys = list(MODELS) if arg == "--all" else [arg]
    for k in keys:
        if k not in MODELS:
            print("Unknown model:", k, "| available models:", list(MODELS))
            return
        if arg == "--all" and MODELS[k]["status"] == "not_free_now":
            continue
        r = ask(k, PROMPT)
        print(f"\n=== {r['model']} | {r['status'][:60]} | {r['seconds']}s ===")
        if r["status"] == "ok":
            print(r["text"][:600])
        if arg == "--all" and not r["status"].startswith("NO_KEY"):
            time.sleep(PROVIDERS[MODELS[k]["provider"]]["delay"])


if __name__ == "__main__":
    main()
