# راهنمای تغییر اسکیما و فیلدها (`CHANGING_THE_SCHEMA.md`)

سامانهٔ نرمال‌ساز بر اساس معماری مبتنی بر پیکربندی (`Schema-Independent / Declarative Mapping`) پیاده‌سازی شده است. در نتیجه با کمترین تغییر در کدهای هسته، امکان اضافه یا کم‌کردن فیلدها وجود دارد.

---

## ۱. اضافه کردن فیلد جدید به پایپ‌لاین

برای اضافه کردن یک فیلد استخدامی جدید (برای نمونه `remote_level` یا `perks`):

### گام اول: افزودن به مدل‌های داده (`Pydantic Models`)
در فایل `src/normalizer_agent/schemas/job_ad.py`:
1. اگر مقدار ورودی می‌تواند ناصاف و اختیاری باشد، فیلد را به کلاس `JobAdRaw` بیفزایید.
2. نوع نهایی، تایپ‌دقیق و استاندارد را در کلاس `JobAd` تعیین کنید.

```python
class JobAdRaw(BaseModel):
    ...
    perks: Any = None

class JobAd(BaseModel):
    ...
    perks: list[str] = Field(default_factory=list)
```

### گام دوم: اعلام نحوهٔ نرمال‌سازی در کانفیگ (`config/fields.yaml`)
در فایل `config/fields.yaml`، نوع رفتار فیلد (`kind`) را مشخص نمایید:

```yaml
fields:
  ...
  perks:
    kind: vocab_list       # یا passthrough، enum_list، integer، vocab_single
    vocab: perk            # نام فایل واژگان در config/vocab/
    allow_composite_split: true
```

انواع رفتارهای موجود (`Kinds`):
* `passthrough`: مقدار بدون تغییر به خروجی منتقل می‌شود.
* `vocab_list`: لیست مقادیر که با واژگان کنترل‌شده تطبیق داده می‌شوند.
* `vocab_single`: مقدار منفرد که باید با واژگان کنترل‌شده منطبق شود.
* `enum_list`: مقادیری که به یک «`Enum`» محدود شده‌اند.
* `integer`: استخراج و پارس عدد صحیح.
* `money`: قوانین تبدیل مبالغ ریالی و تومانی.
* `location`: استخراج استان و شهر بر اساس جغرافیای ایران.

### گام سوم: ساخت فایل واژگان (در صورت نیاز)
اگر فیلد به واژگان کنترل‌شده وابسته است، فایل `config/vocab/<vocab_name>.csv` را با فرمت زیر ایجاد کنید:
```csv
value,category,variants
وام قرض‌الحسنه,مالی,وام|تسهیلات بانکی
ناهار رایگان,رفاهی,ناهار|صبحانه و ناهار
```

### گام چهارم: اعتبارسنجی انطباق
دستور اعتبارسنجی را اجرا کنید تا تطابق مدل و کانفیگ تضمین شود:
```bash
normalizer validate-config -c config
```
مکانیسم `startup_check` به سرعت عدم تطابق بین مدل «`Pydantic`» و فایل کانفیگ را قبل از اجرای هرگونه پردازش گزارش می‌دهد.
