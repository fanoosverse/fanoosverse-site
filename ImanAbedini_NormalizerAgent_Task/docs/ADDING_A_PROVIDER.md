# راهنمای افزودن تأمین‌کنندهٔ جدید مدل زبانی (`ADDING_A_PROVIDER.md`)

سامانهٔ نرمال‌ساز فانوس کاملاً مستقل از ارائه‌دهنده طراحی شده است. برای اضافه کردن مدل یا شرکت ارائه‌دهنده جدید، نیازی به بازنویسی پایپ‌لاین نیست.

---

## ۱. اضافه کردن سرویس‌دهنده‌های سازگار با «`OpenAI`» (بدون کدنویسی)

اگر سرویس‌دهندهٔ جدید از مشخصات استاندارد «`OpenAI Chat Completions`» پشتیبانی می‌کند (نظیر مدلهای محلی `vLLM`، `Ollama`، سرویس‌های ابری ایرانی نظیر ابرآروان یا شرکت‌های خارجی نظیر `Together AI`، `Groq`، `Mistral` و `DeepSeek`):

تنها کافی است مدخل جدیدی در فایل `config/llm.yaml` اضافه کنید:

```yaml
providers:
  - name: "my_new_provider"
    type: "openai_compat"
    enabled: true
    priority: 2
    weight: 1
    base_url: "https://api.example.com/v1"
    model: "deepseek-chat"
    api_key_env: "MY_NEW_PROVIDER_API_KEY"
    timeout_seconds: 30.0
    requests_per_minute: 60
    cost_per_1k_input_usd: 0.0005
    cost_per_1k_output_usd: 0.0015
    params:
      temperature: 0.0
```

سپس کلید دسترسی را در فایل `.env` یا متغیرهای محیطی سیستم قرار دهید:
```bash
export MY_NEW_PROVIDER_API_KEY="your-secret-api-key"
```

---

## ۲. اضافه کردن آداپتور اختصاصی جدید (`Custom Provider Adapter`)

چنانچه سرویس‌دهنده‌ای دارای ساختار پروتکل کاملاً متفاوتی باشد، مراحل زیر را دنبال نمایید:

### مرحله ۱: پیاده‌سازی کلاس آداپتور
یک فایل جدید در مسیر `src/normalizer_agent/llm/providers/` بسازید (برای نمونه `my_provider.py`):

```python
from normalizer_agent.llm.base import (
    LLMProvider, LLMRequest, LLMResponse,
    ProviderTransientError, ProviderPermanentError
)
from normalizer_agent.llm.registry import register, resolve_api_key
from normalizer_agent.settings import ProviderConfig

@register("my_custom_type")
def my_provider_factory(config: ProviderConfig) -> LLMProvider:
    return MyCustomProvider(config)

class MyCustomProvider(LLMProvider):
    def __init__(self, config: ProviderConfig) -> None:
        self.name = config.name
        self.model = config.model
        self.api_key = resolve_api_key(config)
        self.timeout = config.timeout_seconds

    async def complete(self, request: LLMRequest) -> LLMResponse:
        # فراخوانی API با کتابخانه httpx
        # نگاشت خطاها:
        # 401/403 -> ProviderPermanentError
        # 429/5xx -> ProviderTransientError
        ...
        return LLMResponse(
            text=generated_json_text,
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            latency_ms=elapsed_ms,
            provider=self.name,
            model=self.model,
            cost_usd=cost,
        )

    async def aclose(self) -> None:
        pass
```

### مرحله ۲: رجیستر کردن ماژول
ماژول را در فایل `src/normalizer_agent/llm/registry.py` ایمپورت کنید تا دکوراتور `@register` فعال شود.

### مرحله ۳: تست اتصال
با دستور زیر از صحت کارکرد آداپتور اطمینان حاصل کنید:
```bash
normalizer llm-check -c config
```
