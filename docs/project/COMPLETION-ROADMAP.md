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
- [x] 0.4 تنظيف السيرفر: worktrees قديمة وحاويات `aionex-pr872*` متوقفة. يتم بعد نسخة احتياطية. (تم: حاويات `aionex-pr872*` والنسخ الـ static القديمة اتشالت في T-09. أما `/mnt/aionex` فمش worktrees، دي vaults وبيانات استرجاع متسابة عن قصد، وT-21 مرتبط بيها)
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
- [x] 5.2 نموذج AIONEX AI: تفعيل أولوية الباقات المدفوعة من AIOS (توقيع `X-AIONEX-Plan`)، ونتائج اختبار الضغط الحقيقية. جزء الكود: AIOS بقى يبعت `X-AIONEX-Plan` و`-Ts` و`-Sig` موقّعة على نفس bytes الطلب لمسار `ollama:aionex-ai` (owner للمالك، paid للاشتراك المدفوع النشط، free غير كده)، والسر من `AIONEX_AI_PLAN_SECRET_FILE`؛ من غير سر ما فيش headers. (code merged; live verification deferred to pre-launch) الباقي: تركيب السر على الطرفين ونتائج اختبار الضغط. (تم 2026-11-08: السر متركّب على الطرفين. وفي اختبار الضغط، 3 طلبات مجانية شغلت الـ CPU slots المسموحة للمجاني والـ GPU مطفي. طلب مجاني جديد اترفض فورًا بـ 503 وRetry-After، وطلب paid بتوقيع مزوّر اتعامل كمجاني واترفض (`bad_signature`)، وطلب paid موقّع صح اتخدم في 2.3 ثانية على الـ slot المحجوز. التكلفة صفر)
- [x] 5.3 الدفع على Stripe من البداية للنهاية: اشتراك وwebhook وتجديد وإلغاء، بقرار المالك على توقيت التفعيل. الكود: Checkout لكل باقة وفترة (شهري وسنوي) يرجع لـ `https://ai.vip-e.net/<locale>/billing`، ويعيد استخدام عميل Stripe، ويربط الكوبونات والضرائب بـ Stripe أو يرفضها، وIdempotency-Key على كل كتابة. الـ webhooks موقّعة، ومكررة بـ event id، وآمنة على ترتيب الوصول (الحالة والفترة من كائن Stripe)، والأحداث الفاشلة بتتعالج تاني عند إعادة Stripe. الترقية والتخفيض بـ proration، والإلغاء في نهاية الفترة أو فوري، والاستئناف، و`past_due` يقفل المدفوع ويسيب المجاني والتقارير. الصلاحيات (فحص الثغرات لأعلى باقة، والإعلانات، و3D، وAIONEX AI) بتتغير فورًا. الفواتير والإيصالات بتتسجل وتتبعت عبر communication worker، وMRR في لوحة المالك. دليل التشغيل: `docs/project/STRIPE-GO-LIVE-RUNBOOK.md`. (code merged; live verification deferred to pre-launch)

### المرحلة 6: بوابات إطلاق الويب
قائمة التشغيل المرتبة لكل التحققات الحية: `docs/project/PRE-LAUNCH-RUNBOOK.md`.
- [x] 6.1 اختبار 5000 مستخدم حقيقي، مع P95 أقل من 500ms (FR-09 وNS-13). الأداة `scripts/capacity/p6_mixed_load.py` والتحليل والضبط في `P6-CAPACITY-ANALYSIS.md`. (تم 2026-11-08، التشغيل 18: 5000 مستخدم ثابتين 900 ثانية، وحوالي 2.45 مليون طلب من غير ولا خطأ، وP95 للطلبات اللي مش AI حوالي 175ms. الإعدادات النهائية في `docker-compose.p6-capacity-tuning.yml`)
- [ ] 6.2 مراقبة 72 ساعة متصلة (NS-12). الأداة `scripts/ops/p6_72h_observer.py` وشهادة PASS/FAIL. (tooling merged; execution in pre-launch window) (النافذة `p6-72h-20261108t1456z` بدأت 2026-11-08 14:56 UTC. فيه تغيير واحد اتعمل جواها بموافقة المالك: هيدر CSP على بوابة الـ API يوم 2026-11-09 16:03 UTC، وكان reload لـ nginx من غير restart. لازم يتذكر في الشهادة)
- [x] 6.3 مرونة البث وإعادة الاتصال (NS-14A). الأداة `scripts/resilience/p6_stream_fault_matrix.py`. (تم 2026-11-08: إعادة تشغيل الباك إند رجعت في 23 ثانية، وLiveKit فورًا، والنفق في 3 ثواني، من غير تكرار. وكل الحالات الآلية نجحت: الاستكمال من `after_event_id`، و20 إعادة اتصال بـ p95 حوالي 340ms، والتوكن الغلط بيتقفل في أقل من ثانية، والرد بيوصل من الاستعلام لو الحدث الأخير ضاع. اختبارات المتصفح الست لـ NS-14A نجحت على main. أداة القياس اتصلحت في #1051)
- [x] 6.4 استعادة كاملة من R2: التطبيق والمصادقة والميديا (FR-08 وFR-24). الأداة `scripts/recovery/p6_isolated_restore_drill.py`. (تم 2026-11-08: PASS. RPO حوالي 280 ثانية، وRTO حوالي 56 ثانية. الـ canary دخل، وقرأ مشروعه، ونزّل أصل studio بنفس الـ checksum، والبيئة اتشالت كلها. إصلاحات الأداة في #1051: صلاحيات المجلدات، ومسار `aios`، ومسارات الملفات زي الإنتاج، وتسجيل سبب الفشل)
- [x] 6.5 إخراج السيرفر القديم من الخدمة (NS-15 وNS-16). الأداة `scripts/ops/p6_old_server_decommission_verify.py` (قراءة فقط). (tooling merged; execution in pre-launch window) (تم 2026-11-09 بقرار المالك: السيرفر القديم اتلغى خلاص. على السيرفر الجديد، وحدات `aionex-old-rescue-progress` و`aionex-phase22c*-tunnel` كلها inactive وdisabled)
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
- [x] O-12 تغيير توكن نفق cloudflared: جزء من التوكن ظهر بالغلط في مخرجات أمر تشخيص يوم 2026-11-08. المطلوب: إنشاء توكن جديد للنفق من لوحة Cloudflare Zero Trust، ثم وضعه على السيرفر بأمر `read -rsp` يتسلّم للمالك، وبعد كده أنا أعيد تشغيل cloudflared وأتأكد إن الموقع شغال و`aionex-realip-watch` أعاد ربط الثقة. (اتقفل 2026-11-09 بقرار المالك: رفض تغيير التوكن، وده خطر مقبول. الخطر إن أي حد معاه الجزء اللي ظهر من التوكن ممكن يحاول يشغّل connector على النفق. الرجوع عن القرار ده خطوة 10 دقايق)
- [x] O-13 Security Lab: تسجيل `api.vip-e.net` و`ai.vip-e.net` كأهداف فحص. إما target مُدار مربوط بمشروع للمالك (Security Lab ← Managed target)، أو target خارجي بملف تحقق `http_file`. بعدها أنا أشغّل الفحص الكامل عليهم (T-14). (تم 2026-11-09: الهدفين متسجلين كـ managed targets والفحص اشتغل عليهم)
- [ ] O-14 5.1 الصور والفيديو والصوت والأكاديمية والاستوديو موجودين على لوحة التحكم الخاصة (ورا Cloudflare Access) وبحساب Super Owner بس. التشغيل الحي ليهم محتاج المالك يعمل عملية حقيقية واحدة من كل نوع من اللوحة (التكلفة في حدود الـ 25 دولار)، وأنا أراجع السجلات وأكتب الإيصال.

### تقني (يتنفذ في نافذة ما قبل الإطلاق)
- [x] T-20 اختبار 6.1: آخر عائق وصلناله هو نفاد DB pool جوه كل عملية عند حوالي 2500 مستخدم. (تم 2026-11-08، التشغيل 18: PASS. 5000 مستخدم ثابتين لمدة 900 ثانية، وحوالي 2.45 مليون طلب من غير ولا خطأ، وP95 للطلبات اللي مش AI حوالي 175ms. الإصلاحات: #1047 و#1048 و#1049 و#1050، و32 worker، وpool 5+2 بميزانية 230، وPostgres بـ 16 CPU و300 اتصال. الإيصالات `LOAD-RECEIPT-18-*.json`، والسجل الكامل في `P6-CAPACITY-ANALYSIS.md`)
- [x] T-21 Postgres: تعريف volume `aionex-fr06-database-vault` لسه بيشاور على جهاز V1. أي إعادة تشغيل للحاوية كانت بتركّب نسخة V1 القديمة، وده حصل 2026-11-08 الساعة 02:20 UTC لمدة حوالي 7 دقايق. الحاوية دلوقتي مثبتة على `/mnt/aionex/fr09-v3-database-vault/pgdata` عن طريق override على السيرفر. المطلوب تصحيح تعريف الـ volume نفسه (المالك أو صيانة مخططة)، والتأكد إن مفيش أي كتابات مهمة اتسجلت على V1 في الدقايق دي. (تم 2026-11-09:
- [x] T-22 نشر 2026-11-09 بعد T-21:
  - الباك إند وoperations-observer وproject-worker على `core-01c7cf7d` (فيه #1058)، والـ rollout المحروس كانت نتيجته PASS. أول محاولة رجعت تلقائي لأن tag الصورة كان مكتوب ثابت في السكربت، فاتصلح.
  - cloudflared بـ 4 CPU و2 GiB مثبّت في `/etc/aionex/cloudflared-capacity.compose.yml` جوه سلسلة الحاوية، وrealip-watch أكد إن الثقة متغيرتش.
  - خدمات `aionex-realip-watch` و`aionex-scan-egress-guard` و`aionex-runtime-watch` وقفت مع restart الـ docker، ورجعت تشتغل.
  - ZAP لقى 5xx على مسارات Firebase social، وطلع 503 مقصود (`SOCIAL_AUTH_UNAVAILABLE`) لما Firebase مش متضبط. ده مش bug.
- [ ] T-23 مؤقتات AIONEX AI الخلفية (`aionex-ai-cpu-workers` و`enterprise-worker` و`learning-worker`) بتفشل من 2026-11-02 على الأقل، وكلها رافضة بالتصميم: `all_worker_gates_passed=false` و`ENTERPRISE_MODEL_SOURCE_DRIFT` و`LEARNING_QA_NOT_VERIFIED`. مش بتأثر على AIOS (الـ gateway شغال). محتاجة مراجعة في مشروع AIONEX AI.
  - **المشكلة طلعت أكبر من Postgres.** الخمس volumes (`aionex-fr06-{database,asset,local-backup,operations,project-execution}-vault`) كانت معرّفة على أجهزة V1، وV3 كان متركّب فوقها. يعني أي إعادة إنشاء أو restart للسيرفر بتنزّل حاوية واحدة بس (زي redis) كانت ممكن تفتح بيانات V1 القديمة.
  - **الإصلاح:** `MountDevice` في `opts.json` للخمسة اتغيّر للأجهزة `/dev/mapper/aionex-fr09-v3-*-vault`. أخدنا قبلها نسخة احتياطية كاملة اتبعتت للتخزين الخارجي (`e979677c`)، وبعدها عملنا restart لـ dockerd بـ live-restore. الحاويات فضلت شغالة بنفس الـ IDs ومن غير restart، وحاوية مؤقتة على volume قاعدة البيانات فتحت V3 (`postmaster.pid` موجود).
  - **انقطاع:** الحارس `v2_bind.py status` (بوابة ExecStartPre لـ docker) رفض التشغيل لأن ربط `_data` بتاع قاعدة البيانات اختفى، فـ `api.vip-e.net` رجّع 502 لمدة حوالي 78 ثانية (من 16:39:58 لـ 16:41:16 UTC). اتصلح بإعادة الربط (`mount --bind /mnt/aionex/fr06-database-vault .../_data`)، والحارس عدّى.
  - **ملاحظة:** أي حاوية مؤقتة بتستخدم volume قاعدة البيانات بتشيل الربط ده لما تخلص، فلازم يترجع قبل أي restart لـ docker.
  - الإيصال والنسخ الاحتياطية في `/var/lib/aionex-migration/t21-db-volume-20261109`)
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
- [ ] T-14 FR-23E: إعادة تشغيل بوابات FR-23 على commit الإصدار، وفحص Security Lab حي لـ api.vip-e.net وai.vip-e.net، واختبارات DAST معزولة (FR-23C) بعد النشر. (2026-11-08: فحص Security Lab كامل (standard) على `vip-e.net` خلص في 717 ثانية، وكل الأدوات completed: testssl وkatana وhttpx وnuclei (14) وZAP (264). مفيش critical ولا high. الـ medium كلها CSP `unsafe-inline` في الموقع التعريفي على cPanel، والـ low هي HSTS ناقص وBig Redirect. أول محاولة ZAP فيها اترفضت لأن engine ZAP كان فيه spider قديم مش بتاعها، والقفل اتحل يدويًا بسجل audit بعد ما اتأكدنا إن الـ engine فاضي. 2026-11-09:
  - **FR-23E:** بوابات FR-23 (Semgrep وGitleaks وTrivy والتبعيات) عدّت على commit الإصدار `c7565328`.
  - **فحص `api.vip-e.net`:** 684 ثانية، وكل الأدوات completed. فيه high واحدة و3 medium، وكلهم CSP ناقص في ردود الـ API، والإصلاح في #1057 وبينزل بعد 6.2.
  - **فحص `ai.vip-e.net`:** 702 ثانية. مفيش critical ولا high، والـ medium هي CSP `unsafe-inline` في البوابة على cPanel، وده تحسين بعد الإطلاق.
  - **FR-23C:** الأداة `scripts/security/fr23c_isolated_dast.py` بتشغّل نسخة معزولة بقاعدة فاضية، من غير شبكة خارجية ولا منافذ. التشغيل `aionex-fr23c-dast-20261109t141753z` كانت نتيجته PASS:
    - 1995 طلب بين مستخدمين مختلفين على 715 مسار، و631 طلب من غير تسجيل دخول، ومفيش ولا تسريب.
    - القناة الخاصة رفضت المستخدم العادي بـ 403.
    - رفع PHP وSVG وHTML متنكرين اترفض بـ 415، والملف الفاضي بـ 422، والملف الكبير بـ 413.
    - ZAP ما طلعش غير ملاحظات Low وInformational. وأول ما ZAP كشف 500 في mobile-store اتصلح بـ 503 في #1058.
    - البيئة المؤقتة اتشالت بالكامل.
  - **2026-11-09 (16:03 UTC):** هيدر CSP من #1057 اتركّب على الإنتاج بموافقة المالك. التركيب كان reload لـ nginx بس، من غير restart، والنسخة الاحتياطية في `/var/lib/aionex-migration/t14-csp-20261109`. وإعادة فحص `api.vip-e.net` (`1f3fcf84`) خلصت في 690 ثانية، وكل الأدوات completed: صفر critical وhigh وmedium وlow، و6 info بس.
  - **المتبقي:** نشر #1058 بعد نافذة 6.2.
- [x] T-15 نشر إصلاحات FR-23 في الباك إند (تثبيت عنوان التحقق، وصلاحية signed_request لمدة 24 ساعة، ومقارنة توقيعات الدفع، وdefusedxml) وحارس حروف التحكم في nginx (مع T-10). (اتنشر 2026-11-07)
- [x] T-16 بعد بوابة 6.1: تنظيف حسابات اختبار الحمل `synthetic_load_accounts cleanup --execute` وحذف ملف كلمة السر المشترك وملف التصدير. (تم 2026-11-08: 5000 حساب من `p6-20261107t1800z` والـ canary اتعطلوا ومشاريعهم اتمسحت، وملفات كلمات السر والتصدير اتمسحت. إيصالات الحضور فضلت كدليل)
- [x] T-17 جدار egress لـ `security-scan-worker`: منع العناوين الخاصة وloopback وlink-local والـ metadata، أو شبكة منفصلة عن Postgres وRedis والباك إند، لأن أدوات الفحص النشط بتعمل DNS بنفسها (FR23-11). (تم 2026-11-07: `aionex-scan-egress-guard` شغال كخدمة systemd. عامل الفحص وZAP مش واصلين لأي عنوان خاص ولا للسيرفر، والمسموح Postgres وRedis وZAP بس. الاختبار PASS، وفضل شغال بعد إعادة التشغيل)
- [ ] T-18 بناء صورة Hunyuan3D المقواة (`--target release`) ورفعها، ثم إنشاء أو تحديث endpoint على RunPod بـ template جديد مثبت على الـ digest (US بس). بعدها Trivy على الـ digest نفسه، والتجربة الحية للـ PBR من غير fallback (seed مرتين بنفس الـ SHA-256)، وطلب مرفوض للتأكد من الحدود. الخطوات بالتفصيل في الإيصال `FR16D-hunyuan-security-review-20261107.md` (الجزء 4). محتاج موافقة التكلفة O-08.
- [ ] T-19 نشر صورة Blender converter: `docker compose build three-d-converter`، ثم تشغيل الـ sidecar وإعادة إنشاء `three-d-worker` عشان يركب الـ spool. التأكد من `--healthcheck`، وإن `status.json` بيقول Blender 5.2.3، وإن موديل TripoSR جديد طلع له OBJ وFBX وUSDZ ومعاينة، وإن الواجهة بتعرض الصيغ دي بس. (النشر اتعمل 2026-11-07، والبند يتقفل بعد التحويل الحي: الـ sidecar healthy من غير شبكة، و`status.json` بيقول Blender 5.2.3 والصيغ obj وfbx وusdz، و`three-d-worker` راكب الـ spool. تحويل موديل TripoSR حقيقي هيتعمل يوم التجارب في T-08) (2026-11-08: تحويل حي لموديل GLB عبر الـ sidecar في الإنتاج طلع OBJ وFBX وUSDZ ومعاينة في 4 ثواني. اتصلح كمان crash-loop لو طلب في الـ spool مش قادر يتسحب (#1053). فاضل موديل TripoSR حقيقي، وده مستني O-07)

## طريقة التحديث
- كل بند يُعلَّم `[x]` في نفس الـ PR الذي يغلقه، مع رابط PR والإيصال الحي.
- أي قرار جديد من المالك يُضاف إلى "قرارات المالك" بتاريخه.
