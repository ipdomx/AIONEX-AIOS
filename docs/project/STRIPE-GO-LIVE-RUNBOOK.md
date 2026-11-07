# Stripe: دليل التشغيل الحي (Go-Live Runbook)

البند 5.3 في `COMPLETION-ROADMAP.md`. الكود جاهز ومختبر باختبارات تحاكي Stripe بالكامل (`tests/test_p5_stripe_subscriptions.py`). بقرار المالك (2026-11-06) ما فيش أي اختبار بفلوس حقيقية أو حسابات حقيقية قبل نافذة ما قبل الإطلاق. الدليل ده هو اللي يتنفذ وقتها، خطوة بخطوة.

- الكود: `web-dashboard/backend/app/services/stripe_billing.py` و`billing.py`.
- الـ endpoints: `POST /api/v1/billing/checkout` و`/billing/portal-session` و`/billing/subscription/change` و`/billing/subscription/resume` و`/billing/subscription/cancel`، والـ webhook العام `POST /api/v1/billing/webhooks/stripe`.
- لا يوجد DB migration في البند ده. الحالة الإضافية محفوظة في `subscription_metadata` و`invoice_metadata` و`transaction_metadata` و`coupon_metadata`.

## 1. السلوك المتوقع (المرجع اللي بنتحقق منه)

| الحدث | اللي بيحصل محليًا |
|---|---|
| `checkout.session.completed` | الـ checkout يبقى `completed`، والمعاملة `succeeded`، والفاتورة المحلية `paid`، ويتحفظ `cus_...` في `provider_customers.stripe`. لو الـ subscription لسه ما وصلش، بيتعمل اشتراك مؤقت (`provisional`) أي حدث اشتراك بعده يصححه. |
| `customer.subscription.created/updated/paused/resumed` | الحالة والباقة (من `price.id`) وبداية ونهاية الفترة و`trial_end` و`cancel_at_period_end` بتتنسخ من كائن Stripe نفسه. بعدها الصلاحيات بتتحسب من جديد. |
| `customer.subscription.deleted` | الاشتراك `canceled`، وده نهائي (أي حدث أقدم أو "active" بعده يتسجل `stale`). الحساب ينزل للباقة المجانية. |
| `customer.subscription.trial_will_end` | إشعار للمنظمة (in-app + email). |
| `invoice.paid` | فاتورة Stripe تتسجل بأرقامها (subtotal/tax/total/amount_paid والروابط `hosted_invoice_url` و`invoice_pdf`) ومعاملة `succeeded`، وأول فاتورة بتتبنى فاتورة ومعاملة الـ checkout بدل التكرار. إيصال للمنظمة. |
| `invoice.payment_failed` | الفاتورة `past_due` ومعاملة `failed` لكل محاولة (`attempt_count`)، وإشعار تحذير. الحالة نفسها (`past_due`) بتيجي من `customer.subscription.updated`. |
| `charge.refunded` | `BillingRefund` لكل `re_...` (من غير تكرار مع استرداد المالك من اللوحة)، والمعاملة `refunded` أو `partially_refunded`، والفاتورة `refunded` لما يكمل المبلغ. |
| `checkout.session.expired` | الـ checkout `expired`، وحجز الكوبون يتفك، والفاتورة المحلية `void`. |
| أي حدث تاني | يتسجل `ignored` ويرجع 200. |

**سياسة الوصول:** الحساب دايمًا على باقة الاشتراك المؤهل (`active` أو `trialing`، والفترة لسه ما خلصتش)، وإلا على الباقة المجانية `free`. حالة الحساب نفسها تفضل `active` (إلا لو المالك عامل `suspend`)، فالميزات المجانية والتقارير القديمة شغالة.

- `past_due` يقفل الميزات المدفوعة فورًا، ويرجعها أول ما الفاتورة تتدفع ويوصل `updated` بحالة `active`.
- الإلغاء في نهاية الفترة يسيب الوصول لحد `current_period_end`.
- الإلغاء الفوري ينزل الحساب للمجاني فورًا. مفيش `suspended` تلقائي تاني.
- الفحوصات اللي بتتأثر فورًا: `security_entitlement` (فحص الثغرات لأعلى باقة بس)، و`ads_entitlement`، و`three_d_product._billing_access`، و`aionex_ai_plan_signal` (`paid` أو `free`).

**الترتيب والتكرار:** كل حدث بيتسجل مرة واحدة بـ `event.id`. لو فشل يرجع 409 ويتسجل `failed`، وإعادة Stripe لنفس الحدث بتتعالج من الأول (والتغييرات الجزئية بتترجع rollback). ترتيب الوصول ما يفرقش: كل اشتراك فاكر `created` لآخر حدث اتطبق عليه، والأقدم بيتسجل `stale`.

## 2. إعدادات Stripe Dashboard

### 2.1 Products and Prices
1. لكل باقة مدفوعة في تسعير البوابة (Owner > Portal > Pricing) اعمل **Product** في Stripe بنفس الاسم.
2. لكل فترة (`monthly`، `yearly`) اعمل **recurring Price** بنفس المبلغ والعملة (`USD` افتراضيًا) والفترة (`month` أو `year`). الـ `months` في الكتالوج لازم يطابق (1 أو 12).
3. في البوابة، لكل فترة: `checkout_provider = stripe` و`checkout_reference = price_...`. احفظ وانشر، ثم افتح `/api/v1/billing/catalog/public` وتأكد إن `checkout_available = true` للفترات دي.
4. (اختياري) فترة تجريبية: `trial_days` في الفترة بالكتالوج (0 إلى 730). Checkout بيبعتها كـ `subscription_data[trial_period_days]`.
5. الكوبونات: الكوبون المحلي لازم يتربط بـ Stripe وإلا الـ checkout يرفضه (422)، علشان الكارت ما يتخصمش بالسعر الكامل والفاتورة المحلية مكتوب فيها خصم. اعمل Coupon أو Promotion Code في Stripe بنفس القيمة، وابعت `stripe_coupon` (`...`) أو `stripe_promotion_code` (`promo_...`) مع `POST /api/v1/billing/owner/coupons`.

ملاحظة: الإنتاج فيه حاليًا 4 باقات و5 أسعار. راجع إن كل سعر مدفوع بـ `provider = stripe` له `provider_reference` صحيح في وضع الاختبار أولًا، وبعدين في الوضع الحي.

### 2.2 Webhook endpoint
- URL: `https://api.vip-e.net/api/v1/billing/webhooks/stripe` (المسار مسموح في nginx مع rate limit `billing_webhook_per_ip`).
- API version: ثبّت نسخة الـ endpoint. الكود بيقرأ الشكلين: الفترة على مستوى الاشتراك (القديم) أو في `items.data[0]` (من `2025-03-31`)، و`invoice.subscription` أو `parent.subscription_details`، و`invoice.payment_intent` أو `invoice.payments`.
- Events (بالضبط):
  - `checkout.session.completed`
  - `checkout.session.expired`
  - `customer.subscription.created`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
  - `customer.subscription.paused`
  - `customer.subscription.resumed`
  - `customer.subscription.trial_will_end`
  - `invoice.paid`
  - `invoice.payment_failed`
  - `charge.refunded`
- انسخ الـ Signing secret (`whsec_...`) إلى `STRIPE_WEBHOOK_SECRET`. التوقيع بيتراجع بـ `Stripe-Signature` (HMAC-SHA256، وفرق الوقت `PAYMENTS_WEBHOOK_TOLERANCE_SECONDS`، والافتراضي 300 ثانية). أكتر من `v1` مقبول وقت تدوير السر.
- `GET /api/v1/billing/providers/public` بيرجع `stripe_webhook` بالمسار وقائمة الأحداث، للمطابقة.

### 2.3 Customer portal (Settings > Billing > Customer portal)
- فعّل: تحديث وسيلة الدفع، وسجل الفواتير، وتحميل الفواتير، والإلغاء **في نهاية الفترة** (مش فوري).
- تغيير الباقة من الـ portal (اختياري): لو اتفعّل، أضف نفس الـ Prices بس، وخلي الـ proration `create_prorations`. الكود بيستنتج الباقة من `price.id`، فأي تغيير من الـ portal بيوصل صح.
- Default return URL: `https://ai.vip-e.net/en/billing`. الكود بيبعت `return_url` حسب لغة المستخدم: `https://ai.vip-e.net/<locale>/billing?portal=return`.
- لو عملت configuration مخصوص (`bpc_...`)، حطه في `STRIPE_PORTAL_CONFIGURATION_ID`.

### 2.4 الضرائب (Tax)
اختار طريقة واحدة:
- **Stripe Tax:** فعّله في Stripe (Tax settings وorigin address والتسجيلات)، وبعدين `STRIPE_AUTOMATIC_TAX=true`. Checkout بيبعت `automatic_tax[enabled]=true` و`billing_address_collection=required`، والضريبة النهائية بتتسجل من `invoice.paid`.
- **Tax Rates يدوي:** لكل `BillingTaxRate` محلي exclusive اعمل Tax Rate في Stripe بنفس النسبة، وحط الربط في `STRIPE_TAX_RATES=VAT_AE=txr_...,VAT_SA=txr_...`. أي ضريبة exclusive من غير ربط بترجع 409 بدل ما الكارت يتخصم بمبلغ مختلف.

### 2.5 متغيرات البيئة (`deploy/production/.env.payments`)
| المتغير | القيمة |
|---|---|
| `STRIPE_SECRET_KEY` | `sk_test_...` في البروفة، و`sk_live_...` أو `rk_live_...` في الحي |
| `STRIPE_WEBHOOK_SECRET` | `whsec_...` الخاص بالـ endpoint (مختلف بين test وlive) |
| `PAYMENTS_ENVIRONMENT` | `sandbox` مع مفاتيح test، و`live` مع مفاتيح live (أي خلط بيقفل Stripe: `status = blocked`) |
| `PAYMENTS_PORTAL_BASE_URL` | `https://ai.vip-e.net` |
| `STRIPE_AUTOMATIC_TAX` | `true` أو `false` |
| `STRIPE_TAX_RATES` | فاضي أو `CODE=txr_...` |
| `STRIPE_PORTAL_CONFIGURATION_ID` | فاضي أو `bpc_...` |

تحقق: `bash scripts/validate-payments-env.sh deploy/production/.env.payments`.

## 3. بروفة وضع الاختبار (Test mode rehearsal)

بمفاتيح `sk_test_` و`PAYMENTS_ENVIRONMENT=sandbox`، وحساب منظمة تجريبي (مش عميل حقيقي).

1. Stripe CLI:
   ```bash
   stripe login
   stripe listen --forward-to https://api.vip-e.net/api/v1/billing/webhooks/stripe \
     --events checkout.session.completed,checkout.session.expired,customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,customer.subscription.paused,customer.subscription.resumed,customer.subscription.trial_will_end,invoice.paid,invoice.payment_failed,charge.refunded
   ```
   الـ `whsec_` اللي الـ CLI بيطبعه يتحط مؤقتًا في `STRIPE_WEBHOOK_SECRET` للبروفة بس. أو استخدم endpoint وضع الاختبار من الـ Dashboard.
2. اشتراك جديد: من `https://ai.vip-e.net/ar/billing` اختار باقة شهرية وادفع بـ `4242 4242 4242 4242` (أي تاريخ مستقبلي وأي CVC). المتوقع: الرجوع لـ `/ar/billing?checkout=success&session_id=cs_test_...`، والاشتراك `active`، والباقة اتغيرت، وإيصال في الإشعارات، وصف `NotificationDelivery` للـ email.
3. 3D Secure: `4000 0027 6000 3184`. أكمل التحقق، ونفس النتيجة.
4. فشل الدفع عند التجديد: اعمل اشتراك بـ `4000 0000 0000 0341` (الكارت بيتحفظ بس الخصم بيفشل)، وبعدين `stripe test_helpers test_clocks` أو "Advance time" في الـ Dashboard لحد التجديد. المتوقع: `invoice.payment_failed` ثم `customer.subscription.updated` بحالة `past_due`، والميزات المدفوعة اتقفلت (Security Lab يرجع `SECURITY_PLAN_REQUIRED`)، والمجاني شغال.
5. التعافي: من الـ portal غيّر الكارت لـ `4242...` وادفع الفاتورة. المتوقع: `invoice.paid` ثم `active`، والوصول رجع.
6. الترقية: من صفحة الفواتير اختار الباقة الأعلى (الزرار بيبقى "تغيير الباقة"). المتوقع: فاتورة بفرق المدة فورًا (`always_invoice`)، والباقة بتتغير بعد الدفع بس (`pending_if_incomplete`).
7. التخفيض: اختار باقة أقل. المتوقع: تتغير فورًا، والرصيد يتخصم من الفاتورة الجاية (`create_prorations`)، وفحص الثغرات يتقفل لو الباقة الجديدة مش الأعلى.
8. الإلغاء في نهاية الفترة ثم "الإبقاء على الاشتراك": `cancel_at_period_end` يبقى true ثم false، والوصول ما يتأثرش.
9. الإلغاء الفوري (API بـ `immediately=true` أو من الـ Dashboard): الحساب ينزل للمجاني، والتقارير القديمة تفضل مقروءة.
10. الاسترداد: من الـ Dashboard اعمل refund كامل ثم جزئي على فاتورة. المتوقع: `BillingRefund` واحد لكل `re_...`، والمعاملة `partially_refunded` ثم `refunded`. الاسترداد ما بيلغيش الاشتراك، الإلغاء قرار منفصل.
11. الفترة التجريبية (لو مفعلة): `stripe trigger customer.subscription.trial_will_end`، وإشعار "Trial ending soon".
12. التكرار والترتيب: من Dashboard > Webhooks اعمل **Resend** لنفس الحدث مرتين. المتوقع: `duplicate: true` ومفيش صفوف مكررة. وابعت حدث قديم بعد حدث أحدث، والمتوقع `stale`.
13. التوقيع: `curl -X POST .../webhooks/stripe -d '{}'` من غير `Stripe-Signature`. المتوقع 400.
14. Owner dashboard (`/owner/billing`): MRR، والاشتراكات النشطة، والمتأخرة، وقائمة `subscriptions` في `GET /api/v1/billing/owner/overview`.

كروت اختبار إضافية: الرفض العام `4000 0000 0000 0002`، ورصيد غير كافي `4000 0000 0000 9995`.

## 4. قائمة التحقق الحي قبل الإطلاق (بالترتيب، وكل خطوة لها إيصال)

1. [ ] موافقة المالك المكتوبة على التفعيل، والمبلغ والكارت والعميل الداخلي اللي هيتعمل عليه الاختبار.
2. [ ] Stripe account في live mode مفعّل (الشركة والبنك وPayouts)، وStatement descriptor صح.
3. [ ] Products وPrices الحية بتطابق كتالوج البوابة (المبلغ والعملة والفترة)، والـ `checkout_reference` اتحدث للقيم الحية، و`/billing/catalog/public` فيه `checkout_available = true`.
4. [ ] Webhook endpoint حي بالـ URL والأحداث في 2.2 بالضبط، والـ `whsec_` الحي في `STRIPE_WEBHOOK_SECRET`.
5. [ ] Customer portal الحي متظبط زي 2.3.
6. [ ] الضرائب متظبطة زي 2.4 (Stripe Tax أو `STRIPE_TAX_RATES`).
7. [ ] `PAYMENTS_ENVIRONMENT=live` و`sk_live_`/`rk_live_`، و`validate-payments-env.sh` ناجح، و`/billing/providers/public` فيه `stripe.status = ready` و`mode = live`.
8. [ ] نسخة احتياطية من الـ DB قبل التفعيل.
9. [ ] إعادة تشغيل الـ backend، و`/health` و`/ready` بـ 200.
10. [ ] من Dashboard > Webhooks: "Send test event" لـ `invoice.paid` يرجع 200 (`ignored` أو `processed`)، ومفيش 400 أو 503.
11. [ ] اشتراك حي واحد بأرخص باقة شهرية على منظمة المالك الداخلية. المتوقع: `checkout.session.completed` و`customer.subscription.created` و`invoice.paid` كلهم `processed` في `billing_webhook_events`، والباقة والإيصال والـ email.
12. [ ] تحقق الصلاحيات: Security Lab مسموح لأعلى باقة بس، و3D والإعلانات حسب الباقة، و`X-AIONEX-Plan = paid`.
13. [ ] فتح الـ customer portal والرجوع لـ `/<locale>/billing?portal=return`.
14. [ ] Refund كامل للاشتراك ده من الـ Dashboard، ووصول `charge.refunded` بحالة `processed`.
15. [ ] إلغاء فوري، ووصول `customer.subscription.deleted`، والحساب على المجاني.
16. [ ] ما فيش صفوف `failed` في `billing_webhook_events`، ولا تحذيرات `billing.notification.failed` في الـ audit.
17. [ ] تسجيل الإيصال (أرقام الأحداث والمعاملات، بدون أي أسرار) وتعليم 5.3 في الخريطة كتحقق حي.

## 5. الرجوع (Rollback)

- **إيقاف استقبال اشتراكات جديدة بسرعة:** في البوابة رجّع `checkout_provider` للفترات لـ `none` أو `enabled = false`، وانشر. الـ checkout بيرجع 409، والاشتراكات الحالية شغالة والـ webhooks بتتعالج.
- **إيقاف Stripe بالكامل:** فضّي `STRIPE_SECRET_KEY` وأعد التشغيل. `provider_readiness` بيبقى `unconfigured` والـ checkout يتقفل. سيب `STRIPE_WEBHOOK_SECRET` موجود علشان الأحداث المعلقة تتسجل. لو اتشال كمان، Stripe بيعيد المحاولة لحد 3 أيام، ويتعالجوا لما يرجع.
- **خطأ في المفتاح أو الوضع:** `PAYMENTS_ENVIRONMENT` لازم يطابق نوع المفتاح، وإلا Stripe بيتقفل (`blocked`). رجّع القيمتين مع بعض.
- **الكود:** revert للـ PR ده بيرجع السلوك القديم. مفيش migration، فمفيش downgrade للـ DB. البيانات اللي اتكتبت (metadata) ما بتأثرش على الكود القديم.
- **أحداث فشلت:** صلّح السبب، وبعدين Dashboard > Webhooks > Resend للأحداث (`failed` بتتعالج من الأول، و`processed` بترجع duplicate).
- **عميل اتخصم غلط:** Refund من الـ Dashboard (بيوصل `charge.refunded` ويتسجل)، وبعدين إلغاء الاشتراك لو مطلوب. ما فيش أي تعديل يدوي في الـ DB على حالة الاشتراك، Stripe هو المرجع.
