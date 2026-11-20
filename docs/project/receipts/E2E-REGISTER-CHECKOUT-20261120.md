# إيصال: تجربة رحلة المستخدم كاملة (التسجيل لحد Stripe Checkout)، 2026-11-20

**الهدف (قاعدة المالك):** أجرب الرحلة كلها بنفسي وأتأكد إنها شغالة قبل ما المالك يجرب، عشان لما يدخل ما يلاقيش أي خطأ.

## الأداة
- Playwright 1.55 (Chromium headless) شغال على سيرفر الإنتاج، في الحاوية `mcr.microsoft.com/playwright/python:v1.55.0-noble`.
- رقم تليفون تجريبي من Firebase (`aios-7ffd3`)، فمفيش SMS حقيقي بيتبعت. وreCAPTCHA متعمّله stub للأرقام التجريبية بس، لأن المالك جرّب الـ reCAPTCHA الحقيقي بنفسه قبل كده.
- الملفات في `/var/lib/aionex-migration/e2e-register-20261120/` (`e2e.py` و`e2e_pay.py` و`uname_check.py`)، والصور في `shots/`.
- **من غير دفع:** التجربة بتقف أول ما تفتح صفحة Stripe Checkout.

## المشاكل اللي طلعت واتصلحت
| # | المشكلة | الإصلاح |
|---|---|---|
| 1 | الـ `pattern` بتاع اسم المستخدم مش صالح مع الـ v flag، فالاسم الغلط كان بيوصل للسيرفر ويرجع 422 | #1098 |
| 2 | أرقام ‎+1‎ والمكسيك كانت بتترفض (`FIXED_LINE_OR_MOBILE`) | #1099 |
| 3 | CI واقف بسبب containerd CVE-2026-95839 وnext | #1100 |
| 4 | زرار الدفع بيطلع "Failed to fetch" لأن الـ CORS مش سامح بـ `Idempotency-Key` | #1101 |

## النشر (الـ main على `5e512f61`)
- الباك إند: `aionex-aios-backend:...-t28-5e512f61`، بـ `rollout_code2.py` (المرة الأولى build-only، وبعدها التطبيق، وطلع OK في 31 ثانية).
- البوابة: `aionex-aios-portal:ui-5e512f61`، وطلعت OK.
- الموقع الثابت على cPanel (ai.vip-e.net وvip-e.net)، والنسخة الاحتياطية `.aionex-deploy-backups/20261120T-ui-5e512f61`. ملفات `.htaccess` ما اتلمستش.
- الـ preflight `OPTIONS /api/v1/billing/checkout` مع `idempotency-key` بقى بيرجّع 200.

## النتايج بعد النشر
| التجربة | النتيجة |
|---|---|
| تسجيل الدخول ← لوحة التحكم ← الأسعار (Free/Professional/Premium/Business) ← `/billing?plan=professional` ← "Continue to payment" (en) | **PASS**: وصلت لـ checkout.stripe.com (live)، "Subscribe to AIONEX AIOS Professional" بـ 5,000.00 جنيه في الشهر |
| نفس الرحلة بالعربي (ar) | **PASS**: وصلت لـ Stripe Checkout بالعربي، وبنفس السعر |
| كتابة "E2E Test A7!" في خانة اسم المستخدم (en وar) | القيمة بقت `e2etesta7` والحقل صالح، ومفيش أخطاء pattern |
| التسجيل والكود والحساب الجديد (قبل الإصلاحات، رقم ‎+20‎ تجريبي) | PASS (الحساب `e2e-a5`) |

**ملاحظات مش بتوقف حاجة:**
- `/security-lab/access` بيرجّع 403 للمجاني، والواجهة بتتعامل معاه.
- `/auth/me` بيرجّع 401 قبل تسجيل الدخول، وده الطبيعي.
- الـ CSP بيمنع beacon بتاع Cloudflare Insights، وده مجرد كلام في الـ console.
- التسجيل المجاني محدود بعدد معين من كل شبكة في اليوم، وده مقصود.

## التنظيف
- أرقام Firebase التجريبية اتشالت، والقائمة رجعت `[]` زي النسخة الاحتياطية `phone-before.json`.
- حساب `e2e-a5-…@vip-e.net` باسورده اتغيّر لقيمة عشوائية مش محفوظة في أي مكان (مفيش حذف). والملفات المؤقتة (`code.txt` و`a5.pw` و`idtoken.txt`) اتمسحت.

## الخطوة الجاية
المالك يعمل اشتراك Professional حقيقي، وبعده استرداد من `/owner/billing`.
