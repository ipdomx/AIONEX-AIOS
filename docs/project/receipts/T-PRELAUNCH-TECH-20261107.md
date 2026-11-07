# إيصال البنود التقنية قبل الإطلاق — 2026-11-07

**المصدر:** main `cd1d02f1` (PR #1040).
**نسخة قاعدة البيانات قبل البدء:** `pg_dump -Fc` فيها 2178 عنصر، في `/var/lib/aionex-migration/t03-workers-refresh-20261107/db/`.
**Alembic:** على `20261106_0069 (head)` قبل وبعد. مفيش migrations.

كل نشر عمل الآتي:
- اختبار import للصورة الجديدة في حاوية مؤقتة، بنفس البيئة والـ mounts الحية.
- `up -d --no-deps` لكل خدمة لوحدها.
- انتظار الـ healthcheck، ومراجعة اللوجات من غير Traceback.
- التأكد إن ID كل حاوية تانية متغيرش.
- رجوع تلقائي للصورة القديمة بالظبط لو حصل أي فشل.

## T-03 + T-01: العمال
- 19 عامل كانوا على `release-4c6ae500` أو `release-960dab80` أو صورتين بالـ sha256 بس، ودلوقتي كلهم على `*:t01s-cd1d02f1-20261107`. الصور دي فيها:
  - `app/` و`alembic/` و`scripts/` من main
  - `src/aios` من main في `/app/aios-src`
- `PYTHONPATH=/app/aios-src:/workspace/src:/app`، فمحدش بقى بيقرا `src` من الـ checkout القديم `f2527cf3`. ده كان سبب T-01.
- `three-d-worker` و`user-telegram-worker` فشلوا في المرحلة الأولى، لأن `scripts/worker_health_probe` كان ناقص. اترجعوا تلقائي وفضلوا healthy، وبعدها نجحوا بصورة t01s.
- الباك إند وoperations-observer وproject-worker على `*:core-cd1d02f1-20261107`. الـ rollout المحروس عدى PASS، و34 حاوية healthy، والحاويات التانية بنفس الـ IDs. social-publish-worker على نفس الصورة وhealthy.

## T-06: السعة
الإعدادات من `docker-compose.p6-capacity-tuning.yml`:
- الباك إند: 8 CPU، و6 GiB، و`WORKERS=8`، وpool 6+1 من أصل 60، و`REDIS_POOL_SIZE=48`، و`PASSWORD_HASH_THREADS=1`.
- nginx: 2 CPU، باستخدام `docker update` من غير إعادة إنشاء.

قياس الـ 5000 مستخدم لسه في T-07.

## T-10: nginx
- **اكتشاف:** الحاوية كانت شايفة `/etc/nginx/nginx.conf` بنسخة 24 أكتوبر (17684 بايت)، لأن الـ bind mount ماسك الـ inode القديم. التعديلات بعد كده كانت في الملف المؤقت `/tmp` (tmpfs) بس. يعني أي ريستارت كان هيشيل مسارات Meta (P3) وحارس حروف التحكم (FR-23).
- **قبل الريستارت:** ملف المصدر على السيرفر بعد الـ entrypoint طلع مطابق للإعداد الحي. وحاوية مؤقتة بنفس الصورة والـ mounts والمستخدم 101 عدت `nginx -t`.
- **بعد ريستارت متحكم فيه:**
  - الإعداد مطابق للنسخة المحفوظة قبل الريستارت.
  - `api/ready` و`ai.vip-e.net` و`vip-e.net` كلهم 200.
  - `%0A` بيرجع 400.
  - Meta webhook بيرجع 403، وده متوقع لحد ما يتحط رمز التحقق في O-04.

## T-19: Blender converter
- الصورة `aionex-aios-blender-converter:cd1d02f1` مبنية من main، والأرشيف متحقق بالـ SHA-256 جوه الـ Dockerfile.
- الـ sidecar `three-d-converter` شغال من غير شبكة، وread-only، وuid 1000، ومن غير capabilities، وhealthy.
- `status.json`: `blender_version 5.2.3`، والصيغ `obj` و`fbx` و`usdz`، و`thumbnail: true`.
- `three-d-worker` راكب الـ spool `three_d_conversion_spool`.
- تحويل موديل TripoSR حقيقي هيتعمل يوم التجارب في T-08.

## الواجهات
- الـ owner frontend `aionex-aios-owner:ui-cd1d02f1` (تحديثات الفوترة وgrowth-social): PASS.
- الـ portal `aionex-aios-portal:ui-cd1d02f1`: PASS.
- النسخ الثابتة على cPanel (ai.vip-e.net وvip-e.net) فيها صيغ 3D الجديدة. الـ backup هو `.aionex-deploy-backups/20261107T-ui-cd1d02f1`، وملف التحقق الأمني و`.htaccess` بتاع vip-e.net متسابين زي ما هم.

## T-05 و T-09
- **T-05:**
  - توكن Replicate موجود، و`live=true`.
  - مسار provider-input بيرجع 404 من origin، يعني مش محجوب من Cloudflare.
  - الإخفاقات القديمة كانت `identity_media_worker_error/not_started`، و`provider_voice_clone_failed`، و`provider_submission_rejected`.
  - العامل دلوقتي على main، والتأكيد الحي في T-08.
- **T-09:**
  - اتشالت حاويات `aionex-pr872*`.
  - اتشالت 7 نسخ static قديمة (حوالي 16 GB)، واتسابت آخر نسختين للرجوع.
  - اتعمل `builder prune` للكاش الأقدم من 72 ساعة.
  - الـ worktrees في `/mnt/aionex` متسابة.

## الرجوع
كل مجلد تحت `/var/lib/aionex-migration/{t03-workers-refresh,core-t01-t06,t19-blender,t10-nginx,ui-cd1d02f1}-20261107` فيه:
- الصورة القديمة
- ملف rollback override
- سجل الـ rollout

لكل خدمة، الرجوع بيكون `up -d --no-deps` بالـ rollback override.
