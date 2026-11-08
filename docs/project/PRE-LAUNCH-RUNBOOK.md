# دليل نافذة ما قبل الإطلاق (Pre-Launch Runbook)

قرار المالك (2026-11-06): كل الاختبارات الحية بحسابات أو فلوس حقيقية تتعمل مرة واحدة في نافذة ما قبل إطلاق الويب. الدليل ده قائمة واحدة مرتبة. كل بند فيه **معيار نجاح**، و**إجراء المالك** لو البند محتاج حاجة منه. الأوامر كلها جاهزة، والهدف إن النافذة تبقى تشغيل قصير ومكتوب ويتكرر بنفس الطريقة.

قواعد عامة:
- مفيش أي قيمة سرية تتكتب في المستودع أو في الإيصالات. الأسرار تفضل ملفات `0600` على السيرفر.
- كل إيصال يتحفظ تحت `/var/lib/aionex-migration/p6-prelaunch/<UTC>/` بصلاحية `0600`، ويتسجل في `PLAN.json` عن طريق `scripts/project_hub.py`.
- البند يتعلّم `[x]` في `COMPLETION-ROADMAP.md` بعد الإيصال الحي بس، مش بعد دمج الكود.
- الموقع الثابت `vip-e.net` و`ai.vip-e.net` على استضافة cPanel منفصلة (Apache، وعليها WAF ممكن يحظر الـ IP). **ممنوع** أي اختبار حمل عليه. الحمل كله على `api.vip-e.net` بس.

## الترتيب

| # | البند | ليه الترتيب ده |
|---|---|---|
| A | التجهيز وتحقق الأسرار | كل اللي بعده معتمد عليه |
| B | 6.4 الاستعادة الكاملة المعزولة | لازم نتأكد إن النسخة الاحتياطية سليمة قبل أي حمل على الإنتاج |
| C | 6.1 اختبار 5000 مستخدم | أثقل اختبار، ويتعمل والسيرفر لسه ما عليهوش عملاء |
| D | 6.3 مصفوفة أعطال البث | بعد الحمل، لأن فيها إعادة تشغيل حاويات |
| E | Stripe وMeta و3D والفحص الأمني وAIONEX AI وIdentity media | مميزات حية بحسابات حقيقية |
| F | 6.2 مراقبة 72 ساعة | تبدأ بعد آخر تغيير، وأي نشر جديد يعيدها من الأول |
| G | 6.5 إخراج السيرفر القديم | آخر حاجة، وبموافقة المالك |

---

## A. التجهيز

- [ ] **A1. نسخة المصدر على السيرفر.** على NEW host: `cd /opt/AIOS && git fetch origin && git checkout --detach <SHA المعتمد>`. الـ backend بيركّب `..:/workspace:ro` ويقرأ `PYTHONPATH=/workspace/src`. بالتالي **عمال RunPod و`src/aios/gpu_worker/runpod.py` بيقروا `/opt/AIOS/src` من النسخة المسحوبة على السيرفر**، ولو النسخة دي قديمة، أي إصلاح اندمج مش هيشتغل. بعدها اعمل build وأعد تشغيل الحاويات المتأثرة.
  - معيار النجاح: `git -C /opt/AIOS rev-parse HEAD` يساوي الـ SHA المعتمد، و`/ready` يرجّع 200.
- [ ] **A2. سر خطة AIONEX AI.** على AIOS: `AIONEX_AI_PLAN_SECRET_FILE` يشير لملف `0600`. على الـ gateway: `aios_plan_secret_file` يشير لملف **بنفس القيمة**.
  - معيار النجاح: طلب من حساب مدفوع يوصل للـ gateway بـ `X-AIONEX-Plan: paid` بتوقيع صحيح (يظهر في سجل الـ gateway)، وطلب مجاني يتصنف `free`.
  - إجراء المالك: إنشاء السر (32 بايت عشوائية على الأقل) وتركيبه على الطرفين.
- [ ] **A3. قناة تنبيهات المالك.** تنبيهات Telegram الموجودة على السيرفر لبوابة AIONEX AI شغالة، وهي اللي هتنبّه أثناء الـ 72 ساعة.
  - معيار النجاح: رسالة اختبار وصلت للمالك.

## B. 6.4 استعادة كاملة من R2 في مشروع معزول (FR-08 وFR-24)

الأداة: `scripts/recovery/p6_isolated_restore_drill.py`، مع `deploy/restore-drill/docker-compose.restore-drill.yml`.

- [ ] **B1. حساب canary للاستعادة.** قبل آخر نسخة احتياطية مجدولة، أنشئ حسابًا اصطناعيًا واحدًا داخل حاوية الـ backend:
  `python -m app.services.synthetic_load_accounts seed --run-id p6-<YYYYMMDD>t<HHMM>z-canary --count 1 --projects-per-user 1 --password-file <ملف 0600> --export <ملف> --execute`
  (اختياري) ارفع له أصل studio واحدًا واحفظ الـ id.
- [ ] **B2. فحص الحمايات:** `python3 scripts/recovery/p6_isolated_restore_drill.py guard-check --canary-email <email> --canary-password-file <ملف>`
  - معيار النجاح: `GUARDS_PASS`. الأداة ترفض أي اسم مشروع أو شبكة أو volume بتاع الإنتاج، وأي port منشور أو `docker.sock` أو bind غير مسموح به، وأي خدمة غير `fetch` توصل للإنترنت.
- [ ] **B3. التشغيل:** `... run --execute --confirm-project <نفس الاسم> --canary-email ... --canary-password-file ... [--studio-asset-id ...] --output <إيصال>`
  - معيار النجاح: `status=PASS`، و`teardown.clean=true`، والـ smoke ناجح في الخمس فحوص (health وready ودخول الـ canary وقراءة مشروع وجلب أصل ميديا)، وRPO وRTO مسجلين.
  - إجراء المالك: الموافقة على النافذة. السكربت بيقرأ R2 ومفتاح التشفير بس، وعمره ما يلمس حاويات أو volumes أو شبكات الإنتاج.

## C. 6.1 اختبار 5000 مستخدم (FR-09 وNS-13)

التحليل والضبط في `docs/project/P6-CAPACITY-ANALYSIS.md`.

- [ ] **C1. تفعيل real-IP بشكل دائم (شرط للإطلاق):** `python3 scripts/security/fr09_cloudflared_realip_admission.py --apply`، وبعدها نشر nginx مع `docker-compose.fr09-trusted-realip.yml`.
  - معيار النجاح: سجل nginx يظهر فيه IP الزائر الحقيقي بدل IP حاوية cloudflared.
  - إجراء المالك: موافقة على نافذة التغيير.
- [x] **C2. ضبط السعة:** نشر الـ backend مع `docker-compose.p6-capacity-tuning.yml`. القيم النهائية من التشغيل 18 الناجح: 32 worker، وpool 5+2 لكل عملية بميزانية 230، وRedis 64، وArgon2 بـ 2 threads، وPostgres بـ 300 اتصال و16 CPU، وcloudflared بـ 4 CPU.
  - معيار النجاح: `/ready` = 200، ومفيش خطأ في التحقق من الإعدادات.
- [ ] **C3. الحسابات الاصطناعية:** `python -m app.services.synthetic_load_accounts seed --run-id p6-<UTC> --count 5000 --projects-per-user 3 --password-file ... --export ... --execute`
  الإيميلات بتنتهي بـ `@synthetic.loadtest.invalid`، وكل حساب عليه علامة `synthetic_load_account`، ومفيش أي إشعار بيروح للمالك.
- [ ] **C4. نافذة الحمل:** `python3 scripts/capacity/p6_loadtest_exemption.py --address <IP جهاز الحمل العام> --hours 4 --run-id p6-<UTC> --output <dir>/exempt.conf`، وبعدها نشر nginx مع `docker-compose.p6-loadtest-window.yml` (`AIOS_P6_LOADTEST_EXEMPT_DIR=<dir>`).
- [ ] **C5. قياس الحضور على السيرفر:** فعّل `AIOS_FR09_AUTHENTICATED_PRESENCE_ENABLED/RUN_ID/KEY_FILE` (الـ run id على شكل `fr09-...`)، وشغّل `fr09_presence_capture` طول نافذة الثبات.
- [ ] **C6. التشغيل من جهاز منفصل** (Python 3.11 أو أحدث، بدون أي مكتبات خارجية):
  1. `p6_mixed_load.py plan --run-id ...` (من غير شبكة)
  2. `preflight --accounts ... --password-file ...`
  3. `run --execute --confirm-target api.vip-e.net --accounts ... --password-file ... --stop-file /tmp/p6-stop --output <إيصال>`
  - معيار النجاح: `verdict.status=PASS`، يعني P95 لكل طلب غير AI أقل من 500ms، والأخطاء أقل من 1%، ومفيش 5xx storm، و5000 مستخدم داخلين طول نافذة الثبات. وبعدها `scripts/capacity/fr09_evidence_gate.py` على إيصال الحضور والـ DB.
  - إيقاف فوري: لو ظهر حظر WAF أو Cloudflare، أو زاد معدل الأخطاء، أو فشل `/health`، أو `touch /tmp/p6-stop`.
- [ ] **C7. التنظيف:** نشر nginx من غير overlay النافذة (real-IP فقط)، وبعدها `synthetic_load_accounts cleanup --run-id ... --confirm-run-id ... --execute`.
  - معيار النجاح: `count` يرجّع `active=0`، و`exempt.conf` اتمسح.

## D. 6.3 مصفوفة أعطال البث وإعادة الاتصال (NS-14A)

الأداة: `scripts/resilience/p6_stream_fault_matrix.py`. الحالات بتتقري من `PLAN.json`، وأي حالة جديدة من غير سيناريو بتوقف الأداة.

- [ ] **D1. الحالات الآلية** (من أي جهاز، بحساب اصطناعي واحد عنده محادثة): `run --execute --confirm-target api.vip-e.net --email <synthetic> --password-file ...`
  - معيار النجاح: كل الحالات الآلية PASS. يعني إعادة الاتصال في 15 ثانية أو أقل، والاستكمال من `after_event_id` من غير ما يتكرر أي `event_id`، والطلب يتنفذ مرة واحدة بس، والتوكن الغلط يتقفل بسرعة من غير ما يعلّق.
- [ ] **D2. الحالات المُعطِّلة** (على NEW host، `--allow-disruptive`): إعادة تشغيل backend وLiveKit وcloudflared.
  - معيار النجاح: الرجوع في 90 ثانية أو أقل، ومفيش تكرار.
  - إجراء المالك: موافقة، لأن فيها انقطاع قصير.
- [ ] **D3. حالات المتصفح:** الخلفية والمقدمة، وتغيير الشبكة، باستخدام مجموعة Playwright الخاصة بـ NS-14A، والتحقق بـ `scripts/release/ns14a_validate_playwright_artifacts.py`.

## E. المميزات الحية

- [ ] **E1. Stripe live.** (مفيش `STRIPE-GO-LIVE-RUNBOOK.md` في المستودع لحد دلوقتي، والبند ده هو المرجع.) مفاتيح live في ملفات سرية، وwebhook على `https://api.vip-e.net/api/v1/billing/webhooks/stripe` بسر التوقيع.
  - معيار النجاح: اشتراك حقيقي بأقل باقة، والـ webhook يوصل 2xx، والتجديد والإلغاء يتسجلوا، والاسترداد يتعمل.
  - إجراء المالك: تفعيل حساب Stripe live، وتحديد توقيت التفعيل، والدفع بكارت حقيقي.
- [ ] **E2. Meta.** راجع `docs/project/META-APP-REVIEW-PACK.md`.
  1. إعادة ربط الصفحة وحساب Instagram Business بـ OAuth على الـ backend الجديد.
  2. **Verify token للـ webhook:** `META_WEBHOOK_VERIFY_TOKEN_FILE` ملف `0600` (16 حرفًا على الأقل)، ونفس القيمة في لوحة Meta لـ `https://api.vip-e.net/api/v1/social/meta/webhooks` (feed وmessages).
  3. تسجيل فيديوهات المراجعة، وإرسال App Review.
  - معيار النجاح: Meta تتحقق من الـ webhook بنجاح، ونشر منشور تجريبي، ووصول تعليق للصندوق.
  - إجراء المالك: تسجيل الدخول في Meta، وإرسال المراجعة، وBusiness Verification.
- [ ] **E3. 3D على RunPod.** الـ endpointين متوقفين (`max_workers=0`)، ويوم 2026-11-06 الـ scaler ما خصصش worker حتى مع `workersMax=1`.
  - إجراء المالك: فحص لوحة RunPod: توفر الـ GPU في المنطقة، والرصيد، وحالة الـ template والـ image، وسجل الـ endpoint، وبعدها ضبط `workersMax` على 1 أو أكتر.
  - معيار النجاح: مهمة TripoSR حقيقية تخلص بتكلفة محدودة، وGLB يظهر في العارض، والإيصال اتسجل. وبعدها رجّع `max_workers` لقيمة الإنتاج المتفق عليها.
- [ ] **E4. مهلات أدوات الفحص الأمني (بند مفتوح).** testssl وnuclei وصلوا لمهلة 180 ثانية.
  - معيار النجاح: أول فحص كامل على `vip-e.net` (بند 1.5) يخلص من غير timeout، بعد رفع مهلة الأداتين أو تقسيم أهدافهم، والتقرير اتصدّر.
- [ ] **E5. نموذج AIONEX AI.** بعد A2: اختبار ضغط حقيقي على الـ gateway.
  - معيار النجاح: الأولوية للمدفوع ظاهرة في القياس، والحد المجاني شغال.
- [ ] **E6. تشخيص Identity media.** أوامر قراءة فقط على السيرفر حسب PR بند 0.3: آخر التنفيذات الفاشلة وأكواد Replicate.
  - معيار النجاح: السبب الجذري موثق، والعمليتان غير المقبولتين لسه مقفولتين على المستخدم.
  - إجراء المالك: قرار فتح `IDENTITY_MEDIA_UNACCEPTED_OPERATIONS_PUBLIC` من عدمه.
- [ ] **E7. باقي المميزات (المرحلة 5.1):** صور، وفيديو، وصوت، واستوديو، وأكاديمية، ومنشئ المشاريع، وrealtime. تشغيل حقيقي لكل واحدة، وإيصال لكل واحدة.

## F. 6.2 مراقبة 72 ساعة متصلة (NS-12)

الأداة: `scripts/ops/p6_72h_observer.py`. بتعيد استخدام probes الخاصة بـ `ns12_observer_v2.py`، وبتضيف معدل 5xx من سجل nginx، وعمر النسخة الاحتياطية المحلية وعلى R2، وعدد إعادات تشغيل الحاويات.

- [ ] **F1. البدء** (بعد آخر نشر):
  `cp deploy/systemd/aionex-p6-72h-observer@.* /etc/systemd/system/ && systemctl daemon-reload && systemctl enable --now aionex-p6-72h-observer@p6-72h-<YYYYMMDD>t<HHMM>z.timer`
  العينة بتتاخد كل دقيقتين: `api /health` و`/ready`، و`vip-e.net`، و`ai.vip-e.net` باللغات الست (طلب خفيف كل دقيقتين، آمن على WAF الـ cPanel)، وحد Cloudflare Access على `gabarot.vip-e.net`.
  التنبيه بيوصل عن طريق تنبيهات Telegram الموجودة للمالك. ولو تحب، `--notify-command` يمرر العينة الشاذة لنفس المُنبّه.
- [ ] **F2. الشهادة** بعد 72 ساعة: `python3 scripts/ops/p6_72h_observer.py certify --run-id <نفسه> --dir /var/lib/aionex-migration/p6-72h/<run>`
  - معيار النجاح: `status=PASS`، يعني تغطية 72 ساعة أو أكتر من غير فجوة أكبر من دورتين، وتوفر 99.9% أو أكتر لكل هدف (الفشل يتحسب بس لو اتأكد بمحاولة تانية)، وإجمالي 5xx من الـ origin 1% أو أقل، وصفر إعادة تشغيل أو إعادة إنشاء أو OOM، وعمر النسخة الاحتياطية المحلية وعلى R2 26 ساعة أو أقل في كل عينة.
  - أي نشر أثناء النافذة يعيد العدّ من الصفر.
- [ ] **F3. الإيقاف:** `systemctl disable --now aionex-p6-72h-observer@<run>.timer`.

## G. 6.5 إخراج السيرفر القديم (NS-15 وNS-16)

الأداة: `scripts/ops/p6_old_server_decommission_verify.py`. **قراءة فقط**، وعمرها ما تغيّر DNS أو tunnels أو webhooks أو خدمات أو فوترة. الـ IP القديم بيتمرر وقت التشغيل ومش بيتخزن، والإيصال بيحفظ SHA-256 بتاعه بس.

- [ ] **G1. التحقق الآلي** على NEW host: `python3 scripts/ops/p6_old_server_decommission_verify.py --old-ip <IP> [--old-name <host>] --telegram-token-file <ملف> --stripe-key-file <ملف> --output <إيصال>`
  - معيار النجاح: `PASS_AUTOMATED`، أو `PASS_AUTOMATED_MANUAL_PENDING` مع إكمال البنود اليدوية. التحقق بيشمل: مفيش سجل DNS (A وAAAA وCNAME وTXT/SPF) عبر حلّالين DoH بيشاور على القديم، وapi وgabarot خلف Cloudflare، وwebhook Telegram على polling أو على api.vip-e.net، وكل endpoints Stripe على api.vip-e.net، ومفيش ذكر للقديم في `/etc/hosts` أو systemd أو cron أو ssh أو ملفات compose أو env الحاويات، ووحدات `aionex-old-rescue-progress.timer` و`aionex-phase22c*-tunnel` متوقفة.
- [ ] **G2. القائمة اليدوية** (مطبوعة في الإيصال تحت `manual_items`):
  - Meta webhook.
  - Cloudflare Tunnels: الموصل الجديد بس هو اللي سليم.
  - Cloudflare DNS، بما فيه الأسماء اللي مش في القائمة.
  - Stripe، لو مفيش ملف مفتاح.
  - أهداف المراقبة، وقوائم السماح (WAF الـ cPanel، وتوكنات بقيود IP).
  - نسخة أرشيفية أخيرة للقديم مع التحقق من استعادتها.
  - تدوير أو سحب أسرار القديم ومفاتيح SSH.
- [ ] **G3. موافقة المالك الصريحة**، وبعدها إزالة موصل الـ tunnel القديم، وإلغاء الفوترة. **ممنوع الإلغاء بدري لتوفير التكلفة.**

## بعد النافذة

- [ ] تحديث `COMPLETION-ROADMAP.md` (من 6.1 لـ 6.5 تبقى `[x]` بروابط الإيصالات)، وتحديث `PLAN.json` عن طريق `project_hub.py`، وبعدها 6.6 الإصدار النهائي (FR-25).
