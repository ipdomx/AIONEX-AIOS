# AIONEX AIOS: خريطة الإكمال حتى إطلاق الويب

هذه الخريطة تحدد ترتيب العمل الباقي حتى يكتمل الويب. الحالة الحية لكل دفعة (FR) موجودة في `PLAN.json` و`PROJECT-REPORT.md`. أي بند يُغلق هنا يُغلق بعد PR محمي وتحقق حي على الإنتاج، وليس بمجرد دمج الكود.

- تاريخ الإنشاء: 2026-11-04.
- المصدر: مراجعة كاملة للخطة والسيرفر والكود على main `b90705c`.

## قرارات المالك (2026-11-04)

1. **الويب أولًا، والويب كامل:** المشروع يكتمل على الويب بكل مميزاته قبل إطلاق تطبيقات الموبايل.
2. **منصات التواصل والإعلانات:** **Meta فقط** الآن، أي Facebook وInstagram. حساب المطوّر عليها شغال وتمت تجربته. باقي المنصات تؤجل للمرحلة الأخيرة مع إطلاق التطبيق: TikTok وX وLinkedIn وYouTube وSnapchat وPinterest وWhatsApp وGoogle Ads وTikTok Ads.
3. **فحص الثغرات** متاح فقط لمشتركي **أعلى باقة**. المالك له الصلاحية دائمًا.
4. الكود يُبنى بطريقة تسمح بإضافة باقي المنصات لاحقًا كـ "موصل" جديد، من غير إعادة بناء.
5. أي ميزة غير موصولة فعليًا لا تُعرض للمستخدم على أنها شغالة. هذا امتداد لقاعدة FR-20.
6. **(2026-11-06)** كل اختبار حي بحسابات حقيقية أو فلوس حقيقية يتأجل لحد إطلاق الويب الكامل. الكود يُبنى ويُختبر باختبارات الوحدة الآن، ولا يُقال عن أي حاجة إنها شغالة حيًا قبل التحقق.

## وضع البداية (مراجعة 2026-11-03)

| المجال | الكود | الإنتاج |
|---|---|---|
| 3D | مكتمل (TripoSR/Hunyuan على RunPod، والعارض داخل المشاريع) | صفر مهام. Hunyuan محجور أمنيًا. Blender غير موجود |
| فحص الثغرات | مكتمل (ZAP وnuclei وhttpx وkatana وtrivy وgrype وsyft وnikto وtestssl وsemgrep) | صفر فحوصات، والمستخدم يحتاج منحة يدوية من المالك |
| ربط حسابات التواصل | محاكاة، بلا OAuth ولا نشر حقيقي، ولا واجهة للمستخدم | صفحة Facebook وبوتان Telegram، والصحة غير معروفة |
| الإعلانات | Meta تنشئ حملات PAUSED بتوكن المالك فقط. التحليلات والتوصيات محاكاة | توكن Meta غير مركّب في الـ backend الجديد. لا يوجد Google/TikTok Ads |
| الاستوديو والصور والفيديو والصوت والأكاديمية | مكتمل | الحاويات سليمة، وصفر تنفيذ حقيقي |
| Identity media | موجود | 13 من 17 تنفيذًا فاشلًا |
| الدفع | Stripe وPayPal وPaddle | Stripe مُعد بلا معاملات، وPayPal فارغ |
| المصادقة | — | حلقة `/auth/refresh` يحجبها nginx (112 مرة في 48 ساعة) |

## المراحل (بالترتيب)

### المرحلة 0: إصلاحات عاجلة
- [x] 0.1 إيقاف حلقة `/auth/refresh` في الواجهتين: backoff وحد للمحاولات، وتسجيل خروج نظيف عند 401. يشمل ذلك أخطاء Safari "access control checks". (PR #1024، منشور 2026-11-06)
- [x] 0.2 تهدئة أخطاء polling في `telegram-worker`: timeout وbackoff مناسبان، وبلا تسجيل مزعج. (PR #1024 مدموج؛ نشر worker تيليجرام مع إصدار الصور القادم)
- [x] 0.3 تشخيص فشل Identity media (13 من 17) وإصلاحه، أو إخفاء العمليات غير المقبولة (voice_transform وface_swap) عن المستخدم. العمليتان صارتا مقفولتين على المستخدم العادي (`IDENTITY_MEDIA_OPERATION_NOT_ACCEPTED`) إلا بعلم المالك `IDENTITY_MEDIA_UNACCEPTED_OPERATIONS_PUBLIC`، والبوابة تعرض ملاحظة صريحة إنها لسه في اختبار القبول. أكواد الفشل بقت واضحة (سبب HTTP من Replicate، ومقتطف خطأ المزود منقّى)، وخطأ الـ polling المؤقت ما بقاش يُفشل التنفيذ. تأكيد السبب الجذري على السيرفر بأوامر قراءة فقط مذكورة في الـ PR. (code merged; live verification deferred to pre-launch)
- [ ] 0.4 تنظيف السيرفر: worktrees قديمة وحاويات `aionex-pr872*` متوقفة. يتم بعد نسخة احتياطية.
- [x] 0.5 تأكيد سكربت نشر الموقع الثابت على cPanel: صلاحيات 644/755 وقواعد RSC لـ vip-e.net. تم في 2026-11-04 ويحتاج توثيقًا في الريبو. (سكربت `deploy_cpanel.sh`: صلاحيات 644/755، واستثناء `.htaccess` و`_mpa.html` وملف التحقق الأمني و`acme-challenge`)

### المرحلة 1: فحص الثغرات لأعلى باقة
- [x] 1.1 ربط الصلاحية بالباقة: `security_fabric.access_level` يمنح الوصول تلقائيًا لمشترك أعلى باقة نشطة، بدل `SecurityAccessGrant` اليدوي. المالك يبقى owner. (code merged; live verification pending)
- [x] 1.2 إثبات ملكية الموقع بطريقة إضافية هي **DNS TXT**، بجانب ملف `.well-known`. (code merged; live verification pending)
- [x] 1.3 حدود استخدام لكل مشترك: عدد الفحوصات والمواقع شهريًا، مع حد للتزامن. (code merged; live verification pending)
- [x] 1.4 واجهة المستخدم في `vip-frontend`: إضافة موقع، وتحقق، وتشغيل فحص، وتقرير مرتب حسب الخطورة، وخطوات الإصلاح، وتصدير PDF. (code merged; live verification pending)
- [x] 1.5 أول فحص حقيقي على دومين يملكه المالك (vip-e.net)، وإيصال حي. (تم 2026-11-06: الفحص `94feb36d`، 0 حرجة، 1 عالية HSTS اتصلحت. testssl وnuclei وصلوا لحد 180 ثانية ← بند قبل الإطلاق T-04)
- [x] 1.6 إغلاق FR-23، أي الفحص الأمني الشامل للمشروع نفسه. (code review merged; live re-scan in pre-launch window) — PR #1038، الإيصال `docs/project/receipts/FR23-final-security-review-20261107.md`: بوابات Semgrep وGitleaks وTrivy وpip/npm audit، وإصلاحات باختبارات رجوع (منها Next.js RCE في `vip-frontend`). Pillow في TripoSR خطر متبقي لحد إعادة البناء.

### المرحلة 2: الـ 3D
- [x] 2.1 صفحة 3D مستقلة للمستخدم في `vip-frontend`: توليد من صورة أو نص، ومعرض، وعارض، وتنزيل GLB/OBJ. (code merged; live verification pending)
- [ ] 2.2 تجربة حية على TripoSR (RunPod) بتكلفة محدودة بموافقة المالك، وإيصال. ملاحظة 2026-11-06: الـ endpointين على RunPod كانوا متوقفين (`ENDPOINT_PAUSED`، HTTP 409)، فاتضافت معالجة الأخطاء: تسجيل HTTP status وكود المزود، والإيقاف و401/403 أخطاء دائمة بلا إعادة محاولة ولا تحسب على الـ circuit (`THREE_D_PROVIDER_PAUSED` / `THREE_D_PROVIDER_AUTH`)، والتحويل للـ fallback لو واحد بس متوقف، وحالة `provider_state` في رد الـ access. (code merged; live verification deferred to pre-launch)
- [x] 2.3 Hunyuan3D: إعادة بناء الصورة وفحصها أمنيًا (FR-16D)، ثم رفع الحجر. اتعادت كتابة الصورة من صفر: صور pytorch مثبتة بالـ digest بدل الـ base المجهولة، وكود Hunyuan على الـ commit المراجع مع patches بتمنع تنزيل الكود من الـ Hub وأي pickle وأي shell، ومكتبات بـ `--require-hashes`، وأوزان safetensors بس متحققة بـ SHA-256 من revision ثابت، ومستخدم مش root، وحدود على الطلب والمخرج. الأسباب الكاملة للحجر والمعالجة والمخاطر الباقية وخطوات النشر في `docs/project/receipts/FR16D-hunyuan-security-review-20261107.md`. الحجر `HUNYUAN_RUNTIME_SECURITY_APPROVED=False` باقي لحد T-18 وقرار O-10. (code merged; deploy/live verification in pre-launch window)
- [x] 2.4 Blender على السيرفر (أو صورة worker) لتحويل الصيغ والمعاينات. sidecar اسمه `three-d-converter` فيه Blender 5.2.3 متحقق بالـ checksum، من غير شبكة خالص، وكل تحويل في sandbox (timeout وrlimits ومجلدات مؤقتة وfactory startup ومن غير autoexec). بيطلع OBJ وFBX وUSDZ وصورة معاينة، والواجهة بتعرض بس الصيغ اللي اتعملت فعلًا للموديل ده. (code merged; deploy/live verification in pre-launch window)
- [ ] 2.5 قبول 2D (FR-16B)، واستعادة أصل 3D غير فارغ (A04).

### المرحلة 3: إدارة حسابات Facebook وInstagram (Meta)
- [x] 3.1 إطار موصلات عام: OAuth وتخزين التوكن مشفرًا وتجديده، مصمم لإضافة باقي المنصات لاحقًا. (code merged; live verification pending)
- [x] 3.2 OAuth حقيقي لـ Meta: Facebook Login، واختيار الصفحات، وربط حساب Instagram Business. (code merged; live verification pending)
- [x] 3.3 النشر الحقيقي: منشور وصورة وفيديو وReel على الصفحة وإنستجرام، ونشر على عدة حسابات بضغطة واحدة. (code merged; live verification pending)
- [x] 3.4 Worker للنشر والجدولة، مع إعادة المحاولة وسجل نتائج. (code merged; live verification pending)
- [x] 3.5 تقويم المحتوى ومحرر المنشورات، بمساعدة AIONEX AI في الكتابة والهاشتاجات. (code merged; live verification pending)
- [x] 3.6 صندوق وارد موحد: تعليقات ورسائل Messenger وInstagram DM. (code merged; live verification deferred to pre-launch)
- [x] 3.7 واجهة المستخدم في `vip-frontend`: حساباتي، والنشر، والتقويم، والصندوق، والإحصاءات الأساسية. (PRs #1029 و#1031 و#1034: حساباتي، وإنشاء منشور، والتقويم، والصندوق)
- [x] 3.8 تجهيز مراجعة تطبيق Meta (App Review): الصلاحيات المطلوبة، وفيديو الشرح، وسياسة الخصوصية، وحذف البيانات. راجع `docs/project/META-APP-REVIEW-PACK.md`. (code merged; live verification deferred to pre-launch)

### المرحلة 4: إدارة إعلانات Meta وتحليل البيانات
- [x] 4.1 ربط حساب إعلانات المستخدم عبر OAuth (Marketing API)، لا بتوكن المالك فقط. (code merged; live verification deferred to pre-launch)
- [x] 4.2 سحب الأداء الحقيقي (Insights): الإنفاق والوصول والنقرات والتحويلات وCPA وROAS، على مستوى الحملة والمجموعة والإعلان، مع تحديث دوري. (code merged; live verification deferred to pre-launch)
- [x] 4.3 لوحة تحليلات: مقارنة الفترات، وتقسيم حسب الجمهور والمنصة، والتنبيهات. (code merged; live verification deferred to pre-launch)
- [x] 4.4 توصيات حقيقية من AIONEX AI مبنية على الأرقام الفعلية، بدل المحاكاة. (code merged; live verification deferred to pre-launch)
- [x] 4.5 إنشاء الحملات وتفعيلها من المنصة، مع حدود إنفاق وتأكيد صريح وإيقاف تلقائي عند تجاوز الحد. (code merged; live verification deferred to pre-launch)
- [ ] 4.6 تركيب توكن Meta على الـ backend الجديد وتجربة حية محدودة الإنفاق، ثم إيصال.

### المرحلة 5: تحقق حي من باقي المميزات
- [ ] 5.1 تشغيل حقيقي، وإيصال لكل واحد: الصور، والفيديو، والصوت (كلام وموسيقى ودبلجة وتفريغ)، والاستوديو، والأكاديمية، ومنشئ المشاريع، والـ realtime.
- [ ] 5.2 نموذج AIONEX AI: تفعيل أولوية الباقات المدفوعة من AIOS (توقيع `X-AIONEX-Plan`)، ونتائج اختبار الضغط الحقيقية. جزء الكود: AIOS بقى يبعت `X-AIONEX-Plan` و`-Ts` و`-Sig` موقّعة على نفس bytes الطلب لمسار `ollama:aionex-ai` (owner للمالك، paid للاشتراك المدفوع النشط، free غير كده)، والسر من `AIONEX_AI_PLAN_SECRET_FILE`؛ من غير سر ما فيش headers. (code merged; live verification deferred to pre-launch) الباقي: تركيب السر على الطرفين ونتائج اختبار الضغط.
- [x] 5.3 الدفع على Stripe من البداية للنهاية: اشتراك وwebhook وتجديد وإلغاء، بقرار المالك على توقيت التفعيل. الكود: Checkout لكل باقة وفترة (شهري وسنوي) يرجع لـ `https://ai.vip-e.net/<locale>/billing`، ويعيد استخدام عميل Stripe، ويربط الكوبونات والضرائب بـ Stripe أو يرفضها، وIdempotency-Key على كل كتابة. الـ webhooks موقّعة، ومكررة بـ event id، وآمنة على ترتيب الوصول (الحالة والفترة من كائن Stripe)، والأحداث الفاشلة بتتعالج تاني عند إعادة Stripe. الترقية والتخفيض بـ proration، والإلغاء في نهاية الفترة أو فوري، والاستئناف، و`past_due` يقفل المدفوع ويسيب المجاني والتقارير. الصلاحيات (فحص الثغرات لأعلى باقة، والإعلانات، و3D، وAIONEX AI) بتتغير فورًا. الفواتير والإيصالات بتتسجل وتتبعت عبر communication worker، وMRR في لوحة المالك. دليل التشغيل: `docs/project/STRIPE-GO-LIVE-RUNBOOK.md`. (code merged; live verification deferred to pre-launch)

### المرحلة 6: بوابات إطلاق الويب
قائمة التشغيل المرتبة لكل التحققات الحية: `docs/project/PRE-LAUNCH-RUNBOOK.md`.
- [ ] 6.1 اختبار 5000 مستخدم حقيقي، مع P95 أقل من 500ms (FR-09 وNS-13). الأداة `scripts/capacity/p6_mixed_load.py` والتحليل والضبط في `P6-CAPACITY-ANALYSIS.md`. (tooling merged; execution in pre-launch window)
- [ ] 6.2 مراقبة 72 ساعة متصلة (NS-12). الأداة `scripts/ops/p6_72h_observer.py` وشهادة PASS/FAIL. (tooling merged; execution in pre-launch window)
- [ ] 6.3 مرونة البث وإعادة الاتصال (NS-14A). الأداة `scripts/resilience/p6_stream_fault_matrix.py`. (tooling merged; execution in pre-launch window)
- [ ] 6.4 استعادة كاملة من R2: التطبيق والمصادقة والميديا (FR-08 وFR-24). الأداة `scripts/recovery/p6_isolated_restore_drill.py`. (tooling merged; execution in pre-launch window)
- [ ] 6.5 إخراج السيرفر القديم من الخدمة (NS-15 وNS-16). الأداة `scripts/ops/p6_old_server_decommission_verify.py` (قراءة فقط). (tooling merged; execution in pre-launch window)
- [ ] 6.6 الإصدار النهائي للويب (FR-25).

### المرحلة 7 (الأخيرة، مع إطلاق التطبيق)
- [ ] 7.1 منصات التواصل: TikTok وX وLinkedIn وYouTube وSnapchat وPinterest وWhatsApp، كموصلات على إطار المرحلة 3.
- [ ] 7.2 الإعلانات: Google Ads وTikTok Ads على إطار المرحلة 4.
- [ ] 7.3 تطبيقات الموبايل ونشرها على App Store وGoogle Play (FR-18 وG25).
- [ ] 7.4 المؤجلات الرسمية: XR/AR/VR، وFR-06 cold-host، وPayPal وبوابات الدفع الأخرى حسب قرار المالك.

## سجل ما قبل الإطلاق (يُحدَّث دائمًا)
**قاعدة ثابتة (قرار المالك 2026-11-07):** أي بند يتأجل لما قبل الإطلاق، أو أي حاجة لازم المالك يعملها، تُسجَّل هنا فورًا. البند يتشال من هنا بعد التحقق الحي بس. التفاصيل التنفيذية في `PRE-LAUNCH-RUNBOOK.md`.

### مطلوب من المالك
- [x] O-01 موافقة على تفعيل real-IP لحدود الطلبات في nginx (overlay FR09). المشكلة: كل الزوار بيتحسبوا IP واحد (cloudflared)، فالحدود 5 دخول/دقيقة و20 طلب/ثانية على الموقع كله. **عائق إطلاق.** (تم 2026-11-07: الـ real-IP طلع شغال فعلاً، والسجلات بتظهر IP الزائر الحقيقي. اتضافت خدمة `aionex-realip-watch` بتعيد ربط الثقة لوحدها لو حاوية cloudflared اتعاد إنشاؤها)
- [ ] O-02 Stripe: تسجيل webhook `https://api.vip-e.net/api/v1/billing/webhooks/stripe` بالأحداث المذكورة في `STRIPE-GO-LIVE-RUNBOOK.md`، وإعداد Customer Portal، وربط المنتجات والأسعار، ثم بروفة بكروت الاختبار.
- [ ] O-03 Meta (تطبيق `1056852290270430`):
  - Valid OAuth Redirect URI: `https://api.vip-e.net/api/v1/social/oauth/meta/callback`
  - Webhooks: `https://api.vip-e.net/api/v1/social/meta/webhooks`، بالحقول page: feed, messages وinstagram: comments, messages
  - Deauthorize: `/api/v1/social/meta/deauthorize`
  - Data deletion: `/api/v1/social/meta/data-deletion`
- [ ] O-04 Meta: وضع رمز التحقق للـ webhooks على السيرفر (`META_WEBHOOK_VERIFY_TOKEN_FILE`)، بأمر يتسلّم للمالك وقت التنفيذ.
- [ ] O-05 Meta: إعادة ربط الحساب للحصول على صلاحيات الصندوق والإعلانات، ثم تقديم App Review حسب `META-APP-REVIEW-PACK.md`، مع Business Verification.
- [ ] O-06 Meta Ads: توكن إعلانات جديد طويل الأجل، لأن القديم `marketing-api-token` انتهى 2026-10-13.
- [ ] O-07 RunPod: فحص endpoint `aionex-triposr-phase34g-production` (`rrcr2ftk4sqq1j`) من اللوحة، لأن الـ scaler ما شغّلش worker حتى مع workersMax=1 يوم 2026-11-06. الـ endpointين حاليًا workersMax=0. البديل إعادة بناء الـ endpoint.
- [ ] O-08 الموافقة على تكلفة التجارب الحية: 3D، وإعلانات بإنفاق محدود، وStripe live، وAI خارجي إن لزم.
- [ ] O-09 إعدادات GitHub: إضافة فحوصات `FR-23 Security Gates` (Semgrep وGitleaks وTrivy وDependency audit) لقائمة الفحوصات المطلوبة في branch protection على `main` (FR-23).
- [ ] O-10 قرار رفع حجر Hunyuan3D: بعد نجاح T-18 وإيصال القبول الحي بس، يتغير `HUNYUAN_RUNTIME_SECURITY_APPROVED` لـ `True` في PR محمي، ويتنشر الـ backend. الرجوع بيتم بقلب القيمة تاني، وTripoSR يفضل شغال. (الخطوة 6 في إيصال FR-16D)
- [x] O-11 AIONEX AI: إنشاء السر المشترك لأولوية الخطط (T-02)، ووضعه على سيرفر الـ gateway (`aios_plan_secret_file`) وعلى AIOS (`AIONEX_AI_PLAN_SECRET_FILE`) بأمر `read -rsp` على السيرفرين. بعد كده أنا أعمل ريستارت للباك إند وأتأكد من الإشارة. (اتقفل 2026-11-07 من غير ما يحتاج حاجة من المالك: الـ gateway على نفس السيرفر، فالسر اتعمل على الطرفين من غير ما يتطبع)
- [ ] O-12 تغيير توكن نفق cloudflared: جزء من التوكن ظهر بالغلط في مخرجات أمر تشخيص يوم 2026-11-08. المطلوب: إنشاء توكن جديد للنفق من لوحة Cloudflare Zero Trust، ثم وضعه على السيرفر بأمر `read -rsp` يتسلّم للمالك، وبعد كده أنا أعيد تشغيل cloudflared وأتأكد إن الموقع شغال و`aionex-realip-watch` أعاد ربط الثقة.

### تقني (يتنفذ في نافذة ما قبل الإطلاق)
- [x] T-20 اختبار 6.1: آخر عائق وصلناله هو نفاد DB pool جوه كل عملية عند حوالي 2500 مستخدم. (تم 2026-11-08، التشغيل 18: PASS. 5000 مستخدم ثابتين لمدة 900 ثانية، وحوالي 2.45 مليون طلب من غير ولا خطأ، وP95 للطلبات اللي مش AI حوالي 175ms. الإصلاحات: #1047 و#1048 و#1049 و#1050، و32 worker، وpool 5+2 بميزانية 230، وPostgres بـ 16 CPU و300 اتصال. الإيصالات `LOAD-RECEIPT-18-*.json`، والسجل الكامل في `P6-CAPACITY-ANALYSIS.md`)
- [ ] T-21 Postgres: تعريف volume `aionex-fr06-database-vault` لسه بيشاور على جهاز V1. أي إعادة تشغيل للحاوية كانت بتركّب نسخة V1 القديمة، وده حصل 2026-11-08 الساعة 02:20 UTC لمدة حوالي 7 دقايق. الحاوية دلوقتي مثبتة على `/mnt/aionex/fr09-v3-database-vault/pgdata` عن طريق override على السيرفر. المطلوب تصحيح تعريف الـ volume نفسه (المالك أو صيانة مخططة)، والتأكد إن مفيش أي كتابات مهمة اتسجلت على V1 في الدقايق دي.
- [x] T-01 نشر `src/aios/gpu_worker/runpod.py` (PR #1032). (تم 2026-11-07: `src/aios` من main `cd1d02f1` بقى جوه كل صورة في `/app/aios-src`، و`PYTHONPATH=/app/aios-src:/workspace/src:/app` على الباك إند وكل العمال، فمحدش بيقرا الـ checkout القديم. الإيصال `T-PRELAUNCH-TECH-20261107.md`)
- [x] T-02 تفعيل أولوية AIONEX AI: سر مشترك `AIONEX_AI_PLAN_SECRET_FILE` على AIOS، و`aios_plan_secret_file` على الـ gateway. (تم 2026-11-07: الـ gateway اتحدث لـ 02276b9، و`aios_plan_secret_file` بقى مضبوط. AIOS بيوقّع، والـ gateway بيقبل التوقيع الصح ويرفض أي طلب متلاعب فيه. القياس تحت ضغط حقيقي في E5)
- [x] T-03 تحديث صور العمال القديمة (`release-4c6ae500` و`release-960dab80`)، ومنها `security-scan-worker` و`telegram-worker` و`three-d-worker`، لتطابق main: إصلاحات تيليجرام #1024، وملخص الفحص #1027، وثغرات musl/zlib #1035. (تم 2026-11-07: 19 عامل على main `cd1d02f1`، كل واحد بـ rollout محروس وكلهم healthy)
- [x] T-04 مهلات أدوات الفحص: testssl وnuclei بيوصلوا لحد 180 ثانية. التعديل اتوقف بقرار نظام الأمان، ومحتاج مراجعة يدوية بإشراف. (تم 2026-11-07 في #1042: testssl بقى `--ip one` وخلص في 105 ثانية، وnuclei بقى `-as` وخلص في حوالي 585 ثانية بدل حوالي 44 دقيقة، ولكل أداة مهلة خاصة بيها. التأكيد في فحص حي كامل T-14)
- [x] T-05 تشخيص Identity media على السيرفر بأوامر القراءة في وصف PR #1032. (تم 2026-11-07: التوكن موجود والوضع live، ورابط provider-input بيوصل ومش محجوب من Cloudflare. الإخفاقات القديمة كانت من كود العامل القديم (`identity_media_worker_error`) ومن رفض المزوّد. العامل دلوقتي على main، والتأكيد الحي في T-08)
- [x] T-06 تفعيل overlay السعة `docker-compose.p6-capacity-tuning.yml` (8 workers، وDB pool، وRedis) قبل اختبار 5000. (تم 2026-11-07: الباك إند 8 CPU و6 GiB وRedis pool 48 وArgon2 thread واحد، وnginx بقى 2 CPU. القياس نفسه في T-07)
- [ ] T-07 تنفيذ بوابات المرحلة 6 بالترتيب في `PRE-LAUNCH-RUNBOOK.md`: 6.4 ثم 6.1 ثم 6.3، وبعدها التجارب الحية، ثم 6.2 (72 ساعة)، ثم 6.5.
- [ ] T-08 تجارب حية: نشر Meta، والصندوق، والإعلانات، وStripe، و3D، والصور والفيديو والصوت والأكاديمية (البند 5.1).
- [x] T-09 تنظيف السيرفر (0.4). (تم 2026-11-07: اتشالت حاويات `aionex-pr872*` و7 نسخ static قديمة (حوالي 16 GB)، واتنضف build cache أقدم من 72 ساعة. آخر نسختين static متسابين للرجوع. الـ worktrees اللي في `/mnt/aionex` متسابة لأنها شغل تطوير)
- [x] T-10 nginx الإنتاج: التعديلات بتتطبق على `/tmp/aionex-nginx-fr09-realip.conf` (live) وعلى ملف المصدر على السيرفر. لازم ريستارت مُتحكَّم فيه للحاوية يتأكد إنها بتبني نفس الإعداد. (تم 2026-11-07: قبل الريستارت كانت الحاوية شايفة نسخة 24 أكتوبر من الملف، عشان الـ bind mount ماسك الـ inode القديم، يعني أي ريستارت كان هيشيل مسارات P3 وحارس FR-23. اتأكدت إن حاوية جديدة بتبني نفس الإعداد الحي بالظبط ونجح `nginx -t`، وبعدها ريستارت متحكم فيه: الإعداد مطابق، وكل الروابط 200، والـ `%0A` بيرجع 400)
- [x] T-11 إعادة بناء أدوات الفحص المبنية محليًا (`security-build/{gitleaks,httpx,grype,syft,trivy}`) على klauspost/compress 1.18.7 وgo-jose 4.1.6 وx/net 0.62.0، وتحديث `expected_binary_sha256` في كل lock. استثناءات Trivy بتنتهي 2026-12-31 (FR23-10). (تم 2026-11-07 في #1045: الخمس أدوات اتبنت كل واحدة مرتين وطلعت نفس البصمة، واتشالت 4 استثناءات Trivy. صورة الإنتاج بتتبني دلوقتي)
- [x] T-12 **عاجل:** نشر `vip-frontend` بـ Next.js 15.5.29 (البوابة على السيرفر والنسخة الثابتة على cPanel). 15.5.27 فيها ثغرة تنفيذ كود عن بعد من غير تسجيل دخول (GHSA-2464-fhr4-w9xw، FR23-01). (اتنشر 2026-11-07 مع FR-23)
- [ ] T-13 TripoSR (مرتبط بـ O-07، لأن إعادة البناء محتاجة endpoint شغال): Pillow 12.3.0 فيها ثغرات حرجة، والإصلاح Pillow 13 بيتعارض مع rembg (`pillow<13`). لازم إصدار rembg يقبل Pillow 13 أو حل موثق، ثم إعادة بناء الصورة وتشغيلها كمستخدم غير root. **ممنوع رفع workersMax قبلها.** الاستثناء بينتهي 2026-12-15 (FR23-02 وFR23-12). (إصلاح المصدر في PR #1039: rembg 2.0.87 مع Pillow 13؛ البند يتقفل بعد إعادة بناء الصورة والتحقق الحي)
- [ ] T-14 FR-23E: إعادة تشغيل بوابات FR-23 على commit الإصدار، وفحص Security Lab حي لـ api.vip-e.net وai.vip-e.net، واختبارات DAST معزولة (FR-23C) بعد النشر.
- [x] T-15 نشر إصلاحات FR-23 في الباك إند (تثبيت عنوان التحقق، وصلاحية signed_request لمدة 24 ساعة، ومقارنة توقيعات الدفع، وdefusedxml) وحارس حروف التحكم في nginx (مع T-10). (اتنشر 2026-11-07)
- [ ] T-16 بعد بوابة 6.1: تنظيف حسابات اختبار الحمل `synthetic_load_accounts cleanup --execute` وحذف ملف كلمة السر المشترك وملف التصدير.
- [x] T-17 جدار egress لـ `security-scan-worker`: منع العناوين الخاصة وloopback وlink-local والـ metadata، أو شبكة منفصلة عن Postgres وRedis والباك إند، لأن أدوات الفحص النشط بتعمل DNS بنفسها (FR23-11). (تم 2026-11-07: `aionex-scan-egress-guard` شغال كخدمة systemd. عامل الفحص وZAP مش واصلين لأي عنوان خاص ولا للسيرفر، والمسموح Postgres وRedis وZAP بس. الاختبار PASS، وفضل شغال بعد إعادة التشغيل)
- [ ] T-18 بناء صورة Hunyuan3D المقواة (`--target release`) ورفعها، ثم إنشاء أو تحديث endpoint على RunPod بـ template جديد مثبت على الـ digest (US بس). بعدها Trivy على الـ digest نفسه، والتجربة الحية للـ PBR من غير fallback (seed مرتين بنفس الـ SHA-256)، وطلب مرفوض للتأكد من الحدود. الخطوات بالتفصيل في الإيصال `FR16D-hunyuan-security-review-20261107.md` (الجزء 4). محتاج موافقة التكلفة O-08.
- [ ] T-19 نشر صورة Blender converter: `docker compose build three-d-converter`، ثم تشغيل الـ sidecar وإعادة إنشاء `three-d-worker` عشان يركب الـ spool. التأكد من `--healthcheck`، وإن `status.json` بيقول Blender 5.2.3، وإن موديل TripoSR جديد طلع له OBJ وFBX وUSDZ ومعاينة، وإن الواجهة بتعرض الصيغ دي بس. (النشر اتعمل 2026-11-07، والبند يتقفل بعد التحويل الحي: الـ sidecar healthy من غير شبكة، و`status.json` بيقول Blender 5.2.3 والصيغ obj وfbx وusdz، و`three-d-worker` راكب الـ spool. تحويل موديل TripoSR حقيقي هيتعمل يوم التجارب في T-08)

## طريقة التحديث
- كل بند يُعلَّم `[x]` في نفس الـ PR الذي يغلقه، مع رابط PR والإيصال الحي.
- أي قرار جديد من المالك يُضاف إلى "قرارات المالك" بتاريخه.
