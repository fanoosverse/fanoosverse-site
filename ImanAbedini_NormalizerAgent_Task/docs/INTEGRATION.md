# راهنمای یکپارچه‌سازی و اتصال به هماهنگ‌کننده (`INTEGRATION.md`)

این راهنما نحوهٔ استفاده از عامل نرمال‌ساز را در قالب کتابخانهٔ پایتون، اتصال به صف‌های پیام پایپ‌لاین فانوس (`Coordinator`)، وب‌سرویس و ابزار خط فرمان شرح می‌دهد.

---

## ۱. استفاده به صورت کتابخانهٔ پایتون (`Python In-Process API`)

ساده‌ترین روش برای استفاده از نرمال‌ساز در کدهای پایتون به شکل زیر است:

```python
import asyncio
from normalizer_agent.interface.api import Normalizer

async def run():
    # بارگذاری تنظیمات و راه‌اندازی کش و مسیریاب
    normalizer = await Normalizer.from_config("config")
    try:
        raw_record = {
            "document_id": "job_12345",
            "collector": "jobinja",
            "source_type": "job_posting",
            "role_title": "توسعه‌دهنده پایتون",
            "skills_required": ["پایتون", "جنگو", "داکر"],
            "salary_min": "۴۰ میلیون تومان",
            "salary_max": "۶۰ میلیون تومان",
            "text": "متن کامل آگهی...",
            "content_hash": "a1b2c3d4e5f6...",
            "collected_at": "2026-08-30",
        }
        # پردازش یکتای رکورد
        result = await normalizer.normalize(raw_record)
        print("Status:", result.status)
        if result.record:
            print("Canonical Skills:", result.record.skills_required)
            print("Salary Min (IRR):", result.record.salary_min)
    finally:
        await normalizer.aclose()

asyncio.run(run())
```

---

## ۲. اتصال به هماهنگ‌کنندهٔ پایپ‌لاین (`Fanos Coordinator Integration`)

کلاس پایهٔ `AbstractCoordinatorAdapter` در مسیر `src/normalizer_agent/interface/coordinator.py` برای اتصال به زیرساخت‌هایی نظیر `Celery`، `Kafka`، `RabbitMQ` یا `Temporal` طراحی شده است.

### پیاده‌سازی مرجع:
```python
from normalizer_agent.interface.coordinator import ReferenceCoordinatorAdapter, CoordinatorMessage

# ساخت آداپتور با یک نمونه فعال از Normalizer
adapter = ReferenceCoordinatorAdapter(normalizer)

# پیام ورودی از صف کار
message = CoordinatorMessage(
    id="msg_001",
    body=raw_record,
    trace_id="trace_abc_123"
)

# پردازش و ارسال خودکار نتایج بر اساس وضعیت
result = await adapter.process_item(message)
# - رکوردهای موفق (normalized) -> صف ذخیره‌سازی اصلی
# - رکوردهای مشکوک (needs_review) -> صف بازبینی انسانی
# - رکوردهای خراب (rejected / failed) -> صف پیام‌های مرده (DLQ)
```

---

## ۳. اجرای وب‌سرویس (`Microservice REST API`)

برای استقرار مستقل در زیرساخت ابری یا کانتینر `Docker`، سرویس مبتنی بر `FastAPI` آماده استفاده است:

```bash
# اجرای سرویس با سرور Uvicorn
uvicorn normalizer_agent.interface.service:app --host 0.0.0.0 --port 8000
```

### نقاط پایانی (`Endpoints`):
* `GET /health`: بررسی سلامت سامانه، نسخه و سرویس‌دهنده‌های فعال.
* `GET /metrics`: دریافت شمارنده‌های آماری کارایی و تعداد رکوردهای نرمال‌شده.
* `POST /normalize`: دریافت بدنهٔ یک رکورد و بازگرداندن پاکت استاندارد.
* `POST /normalize/batch`: ارسال مجموعه‌ای از رکوردها برای پردازش هم‌زمان.

---

## ۴. رابط خط فرمان (`CLI`)

برای انجام تست‌های سریع، اعتبارسنجی کانفیگ و پردازش فایل‌های دسته‌ای:

```bash
# اعتبارسنجی فایل‌های پیکربندی با ساختار داده
normalizer validate-config -c config

# ارسال پروب آزمایشی به سرویس‌دهنده‌های LLM فعال
normalizer llm-check -c config

# پردازش یک فایل JSON یا JSONL و تولید خروجی
normalizer run -i raw_jobs.jsonl -o normalized_jobs.jsonl -c config
```
