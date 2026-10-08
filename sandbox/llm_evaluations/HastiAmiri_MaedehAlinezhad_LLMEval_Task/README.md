# LLM Connection Code (Task 1)

This code connects to the selected free-API models and sends requests. All services use the OpenAI format, so everything works through a single `ask()` function.

## Setup
1. `pip install -r requirements.txt`
2. Copy `.env.example` to `.env` and put in your real keys (only the keys for the services you use).
3. Run: `python example_usage.py` (or `python example_usage.py --all`)

## Getting the keys
| Service | URL | Models |
|---|---|---|
| OpenRouter | openrouter.ai/keys | Nemotron 3 Ultra (and other `:free` models) |
| Google AI Studio | aistudio.google.com/apikey | Gemini Flash |
| Mistral | console.mistral.ai | Devstral |
| Groq | console.groq.com | Llama 3.3 70B |
| NVIDIA | build.nvidia.com | Kimi K2.6 |

## Usage example in code
```python
from llm_client import ask
r = ask("nemotron-3-ultra", "Hello!")
print(r["status"], r["seconds"], r["text"])
```
If `status` is not `ok`, the cause of the error is written there.

## Model status (tested up to 2026-10-08)
- `nemotron-3-ultra`: tested. 5 prompts succeeded, 1 temporary error on the NVIDIA side, 1 network 403, 1 prompt not run.
- `gemini-flash`, `llama-3.3-70b`, `devstral`, `kimi-k2.6`: not tested (no key or access). The model ID is based on the documentation and may need correction; use `list_models("service-name")` to find the correct ID.
- `deepseek-v4-flash`, `qwen-3.6-plus`: no longer have a free version on OpenRouter.

## Security notes
- Never write an API key in a notebook, in code or in Git. Keep it only in `.env` (which is in `.gitignore`).
- If a key leaks anywhere, delete it from the service dashboard immediately and create a new one.
- Free plans may use the input data to train models; do not send confidential data.
- The OpenRouter free limit is about 20 requests per minute and 50 per day, and failed requests are counted too.
- The limits of the other services (Google, Groq, Mistral, NVIDIA) differ and may change. This is why a `delay` pause is placed between requests in `--all` mode.

## Common problems
- `HTTP 403`: usually the IP/region is blocked. Use a system-wide VPN (not a browser extension) with a US/Europe location, then restart the kernel/program.
- `HTTP 404`: the model ID has changed. Run `list_models()`.
- `HTTP 429`: you hit the rate limit; wait a few minutes.
