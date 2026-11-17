# دليل التشغيل: سيرفر إنتاج AIONEX AIOS

**الدليل ده لمين:** لأي حد بيشغّل السيرفر أو بينشر عليه.

**ده خلاصة اللي اتعلمناه في نوفمبر 2026.** التفاصيل الكاملة لكل حدث موجودة في الإيصالات تحت `docs/project/receipts/`، وفي الـ roadmap.

## 0. قواعد ثابتة

1. **كل تغيير في الإنتاج لازم يكون له نسخة احتياطية وطريقة رجوع.** ولو التغيير كبير أو فيه صرف فلوس، المالك لازم يوافق الأول.
2. **الأسرار:**
   - بتتحط بـ `read -rsp` في ملفات `0600`، وعمرها ما بتتطبع أو تتكتب في الريبو.
   - **ممنوع** تطبع `docker inspect .Config.Cmd` بتاع cloudflared، لأن فيه توكن النفق.
3. **ممنوع** إضافة أي حاجة لـ `.gitleaksignore`، أو تعطيل حماية الفروع، أو تخطي CI. أي PR بيتدمج بس لما كل الفحوصات تبقى خضرا.
4. **الفحص الأمني** للدومينات اللي المالك متحقق منها أو مسجّلها بس.

## 1. شكل السيرفر

| البند | القيمة |
|---|---|
| مشروع compose | `web-dashboard`، في `/opt/AIOS/web-dashboard`، و`.env.production` جنبه |
| عدد الحاويات | 35 حاوية |
| الدخول العام | عن طريق cloudflared ← nginx (`8080` للـ API، و`8082` للبوابة، و`8081` للوحة التحكم الخاصة) |
| المنافذ المكشوفة على الإنترنت | **مفيش** |
| قواعد البيانات (FR09 V3) | خمس مخازن على أجهزة `/dev/mapper/aionex-fr09-v3-<role>-vault` |
| Docker | على قرص منفصل `aionex-container-runtime-vault-v2`، ومتركّب على `/var/lib/docker` |
| ملفات العمليات | كل عملية ليها مجلد في `/var/lib/aionex-migration/<task>-<date>/`، فيه السكريبتات والـ overrides والسجلات والإيصالات |

**سلسلة ملفات الـ compose:**
- كل حاوية شايلة سلسلة الملفات اللي اتعملت بيها في الـ label `com.docker.compose.project.config_files`.
- أي تحديث لازم يعيد استخدام السلسلة دي بالظبط، ويزوّد عليها override جديد فيه `image:` بس. كده الإعدادات الحالية كلها بتفضل زي ما هي.

## 2. النشر المحروس (Guarded rollout)

**المرجع الحالي:** `/var/lib/aionex-migration/t25-dnspython-20261117/rollout_dns.py`.

**الخطوات:**
1. **ابني الصورة الجديدة** كطبقة فوق الصورة الشغالة، أو من الكود، بـ tag جديد. **عمر ما تكتب فوق tag شغال.**
2. **اختبرها قبل الإنتاج** بـ `--network none`:
   - الـ import.
   - النسخة.
   - **المستخدم:** لازم يفضل زي الأصلي. مثال: عامل الفحص بيشتغل بـ `1000:1000`، ولما الطبقة الجديدة رجّعته root، الـ rollout رجع تلقائي يوم 2026-11-13.
3. **انشر خدمة واحدة في المرة:**
   - `docker compose ... -f <سلسلة الـ label> -f <svc>.new.override.yml up -d --no-deps --no-build <svc>`
   - استنى لحد ما الحاوية تبقى healthy.
   - اتأكد إن الـ image هي الجديدة، وإن **باقي الحاويات ما اتغيرتش** (نفس الـ IDs).
4. **لو أي حاجة فشلت:** ارجع لملف `<svc>.rollback.override.yml`، ووقّف السلسلة كلها.
5. **الباك إند آخر واحد:** الـ recreate بتاعه بياخد حوالي 30 ثانية. بعدها اتأكد إن `https://api.vip-e.net/ready` بيرجّع 200.
6. **سجّل الإيصال:** `ROLLOUT-RECEIPT.json`، وسطر في الـ roadmap.

## 3. بوابة FR09 وإعادة تشغيل dockerd

**البوابة:** `docker.service` فيه `ExecStartPre` بيتحقق من 3 حاجات:
- `v2_vault_mount.py status`
- `v2_bind.py status`
- `v3_production_guard.py host`

**الشرط:** `/var/lib/docker/volumes/aionex-fr06-database-vault/_data` لازم يكون bind لـ `/mnt/aionex/fr06-database-vault`.

**لو أي حاوية مؤقتة استخدمت الـ volume ده:** أعد الـ bind **قبل** أي restart لـ dockerd:
```
mount --bind /mnt/aionex/fr06-database-vault /var/lib/docker/volumes/aionex-fr06-database-vault/_data
```
لو ما عملتش كده، dockerd مش هيقوم، والـ API هيقع. ده اللي حصل يوم 2026-11-09، ونزل لمدة 78 ثانية (T-21).

**بعد أي restart لـ dockerd:** أعد تشغيل `aionex-realip-watch` و`aionex-scan-egress-guard` و`aionex-runtime-watch`.

**الأفضل:** تتجنب restart dockerd خالص. `live-restore` مفعّل.

## 4. قرص Docker وبناء الصور الكبيرة

**المراقبة:** `host-capacity-guard.py`، وبيشتغل مع `aionex-runtime-watch.timer`. بيراقب `/` و`/var/lib/docker` (المقياس `docker_disk_pct`)، وبينبّه عند 70% و85%.

**قبل ما تبني صورة كبيرة على السيرفر** (صور الـ 3D أكتر من 30 GB):
- اتأكد إن المساحة الفاضية **أكتر من ضعف** حجم الصورة.
- بعد ما ترفعها، امسح الـ tags القديمة واعمل `docker builder prune -f --keep-storage 20GB`.

**ليه:** يوم 2026-11-13، بناء صور Hunyuan ملا القرص، و`three-d-converter` وقع 5 مرات (T-26).

## 5. صور الـ 3D وRunPod

**البناء والفحص:**
- صور `ipdomx/aionex-triposr` و`ipdomx/aionex-hunyuan3d` بتتبني من `infra/runpod/*`.
- الـ build نفسه بيحمّل الموديلات الحقيقية على CPU كمستخدم التشغيل، وبيشغّل كل الخطوات اللي مش محتاجة GPU. **لو الـ build فشل، اقرا السبب، وما تتخطاهوش.**
- **الفحص:** Trivy بصورة `aionex-aios-security-tools` والـ docker socket للقراءة بس. الشرط صفر HIGH/CRITICAL.
- **الرفع:**
  - بيانات Docker Hub في `/opt/AIOS/web-dashboard/secrets/DOCKERHUB.env`.
  - اعمل login بـ `--password-stdin`، وبعدين push، وبعدين logout.
  - لو الـ push وقف (السرعة صفر لمدة طويلة)، وقّفه وأعده.

**إدارة RunPod:**
- **الـ API:** GraphQL على `api.runpod.io`، بالـ UA `aionex-aios-ops/1.0` (الـ REST بيدّي Cloudflare 1010). المفتاح في `/opt/AIOS/web-dashboard/secrets/RUNPOD_GPU.env`، و**ممنوع يتطبع**.
- **الأدوات:** في `/var/lib/aionex-migration/t13-triposr-01c7cf7d/`:
  - `rp.py`: دالة `gql()`.
  - `rp_switch.py <endpoint> <image|-> <name> <workersMax>`: بتعمل template جديد مثبت على الـ digest، وبتغيّر `workersMax`.
- **تغيير الـ template:**
  - `saveEndpoint` **مش** بيغيّر الـ template. لازم `updateEndpointTemplate`.
  - بعد التغيير، **استنى دقيقة** قبل أول job، عشان الـ job ما يروحش للصورة القديمة.
- **الـ endpoints:**
  - TripoSR: `rrcr2ftk4sqq1j`.
  - Hunyuan: `z3jr89oynrk2c7` (US بس، AMPERE_48).
  - الاتنين على `workersMax=0` لحد الإطلاق (O-16).
- **بعد أي تجربة حية:** رجّع `workersMax=0` على طول، واتأكد إن `currentSpendPerHr = 0`.

## 6. المراقبة والتنبيهات

| الـ timer | الوظيفة |
|---|---|
| `aionex-runtime-watch` | أعطال الحاويات وسعة السيرفر |
| `aionex-owner-alerts` | ملخص الحالة للمالك |
| `aionex-ai-runpod-cost-guard` | تكلفة RunPod |
| `aionex-ai-pressure-guard` | الضغط على AIONEX AI |
| `aionex-fr09-realip-peer-watch` | سلامة الـ IP الحقيقي خلف cloudflared |
| `aionex-ns12-observer`، و`aionex-p6-72h-observer@<run>` | مراقبة 72 ساعة |

- **طريقة المراقبة:** المراقبة الطويلة بتتعمل بـ `setsid nohup`، والسجلات بتتكتب في مجلد العملية.
- **ملحوظة:** `pgrep` بيلاقي سطر الأمر بتاعه هو كمان، فبيدّي نتيجة "RUNNING" غلط.

## 7. النسخ الاحتياطي والاستعادة

- **النسخ:** `backup-worker` بيعمل نسخ مشفرة على R2.
- **البروفة:** في مشروع compose معزول، بـ `scripts/recovery/p6_isolated_restore_drill.py` (6.4، والإيصال في الـ roadmap).
- **بعد البروفة:** امسح بيئة البروفة كلها بـ `down -v`. **لازم تتأكد إن مفيش أي volume أو شبكة من الإنتاج اتلمست.**

## 8. حوادث متكررة وحلها

| العَرَض | السبب المعتاد | الحل |
|---|---|---|
| API بيرجّع 502 بعد restart لـ dockerd | بوابة FR09 (`docker_nested_vault_wrong_database`) | أعد الـ bind (القسم 3)، وبعدين شغّل docker |
| `three-d-converter` بيقع ويقوم | مساحة القرص، أو ملف root متساب في الـ spool | امسح المساحة، وأي اختبار يدوي يشتغل كـ `-u 1000:1000` |
| CI بيفشل بـ `cache entry no longer exists` | cache بتاع GitHub runner | أعد تشغيل الـ job اللي فشل بس |
| `pip-audit` بيوقف كل الـ PRs | ثغرة جديدة اتنشرت في حزمة | ارفع النسخة في الريبو، وبعدين اعمل rollout محروس للإنتاج (زي T-25) |
| job في RunPod بيفشل وقت التشغيل | فرق نسخ بين الموديل والمكتبات، أو الصلاحيات | صلّحه في الكود، وزوّد فحص في الـ build يمسك العطل ده |

## 9. قبل الإطلاق

- **الترتيب:** `PRE-LAUNCH-RUNBOOK.md`.
- **Stripe:** `STRIPE-GO-LIVE-RUNBOOK.md`.
- **Meta:** `META-MARKETING-NEW-SERVER-RUNBOOK.md`.
- **آخر خطوة:** مراقبة 72 ساعة (6.2) بالـ timer `aionex-p6-72h-observer@<run>.timer`، وبعدها الاعتماد النهائي.
