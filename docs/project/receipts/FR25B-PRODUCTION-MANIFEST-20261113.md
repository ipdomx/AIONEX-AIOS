# FR-25B: سجل نسخ الإنتاج، 2026-11-13

**وقت الالتقاط:** 2026-11-13 06:58:10 UTC.

**الملف الكامل على السيرفر:** `/var/lib/aionex-migration/FR25B-MANIFEST-20261113.json`. فيه لكل خدمة: الصورة، والـ image ID، والـ digest، والمستخدم، والحالة، وعدد الـ restarts.

## الثوابت

| البند | القيمة |
|---|---|
| كود التطبيق | main `01c7cf7d`، وده بيشمل الباك إند والـ observer والـ project worker والـ 18 عامل وعامل الفحص الأمني |
| الواجهات | `ui-cd1d02f1` (مفيش تغيير في الواجهات على main من بعدها) |
| قاعدة البيانات | Alembic `20261106_0069` |
| إعداد nginx الحي | `d21cc519051e18ae5a36e425dc029bf0e63c1d0772b2516e85a5fd904e18894b` (فيه CSP بوابة الـ API) |
| بوابة AIONEX AI | الإصدار `02276b9c50f0` |
| مخازن البيانات | الخمسة على أجهزة V3 `/dev/mapper/aionex-fr09-v3-*-vault` (T-21) |
| الحاويات | 35 حاوية، وكلها healthy (cloudflared مالوش healthcheck) |

## الصور

| الخدمة | الصورة |
|---|---|
| backend و social-publish-worker | `aionex-aios-backend:core-01c7cf7d-krb5` (`e32c48c8…`) |
| operations-observer | `aionex-aios-operations-observer:core-01c7cf7d-krb5` (`3dfbe329…`) |
| project-worker | `aionex-aios-project-worker:core-01c7cf7d-krb5` (`1f587731…`) |
| 13 عامل على صورة الباك إند (الصوت، والتصميم، والاستوديو، والتواصل، والنسخ الاحتياطي، والمعالجة الأمنية، و3D، وuser-telegram) | `…backend_release-4c6ae500:t01s-01c7cf7d-krb5` (`7851ebf3…`) |
| media-worker و academy-course-worker | `…media-worker_release-960dab80:t01s-01c7cf7d-krb5` (`eb37bbfd…`) |
| design-image-derivative-worker | `…image-derivative-worker_release-4c6ae500:t01s-01c7cf7d-krb5` (`02085ea1…`) |
| video-provider-worker | `…video-provider-worker_release-960dab80:t01s-01c7cf7d-krb5` (`1195ba46…`) |
| identity-media-worker | `aionex-aios-refresh-identity-media-worker:t01s-01c7cf7d-krb5` (`61b3d829…`) |
| telegram-worker | `aionex-aios-refresh-telegram-worker:t01s-01c7cf7d-krb5` (`ebea7912…`) |
| security-scan-worker | `aionex-aios-security-tools:t11s-01c7cf7d` (`181d9b6b…`)، بالمستخدم 1000:1000 |
| three-d-converter | `aionex-aios-blender-converter:cfe80e6f` (`9b9504ee…`) |
| postgres | `aionex-aios-postgres:16-hardened-krb5` (`81b99b6c…`) |
| nginx | `aionex-aios-nginx:hardened` (`a174fd47…`) |
| frontend و portal | `aionex-aios-owner:ui-cd1d02f1` و `aionex-aios-portal:ui-cd1d02f1` |
| الصور الخارجية | cloudflared `2026.7.0@sha256:5e498616…`، وredis `7-alpine@sha256:ff02b58f…`، وZAP `2.17.0@sha256:781a2bda…`، وLiveKit، وegress، وcoturn، وollama، وكلها مثبتة بالـ digest |

## الملاحظات

- **project-worker، restart واحد:** حصل 2026-11-11 17:04:50 UTC وقت تحديث Postgres، يعني فقد الاتصال بقاعدة البيانات لمدة 9 ثواني ورجع لوحده.
- **three-d-converter، 2 restart:** حصلوا 2026-11-11 حوالي 17:40 UTC، لما مساحة القرص بتاع Docker خلصت مؤقتًا وقت فحص Trivy لصورة Hunyuan3D (`No space left on device` في الـ spool بتاعه بس). المساحة رجعت تاني، وبعدها اتمسح build cache قديم (`docker builder prune --keep-storage 30GB`)، والمساحة الفاضية بقت 128 GB. سجلات postgres والباك إند وredis وbackup-worker وnginx مفيهاش أي خطأ مساحة في الفترة دي.
- **تحديث كود العمال لـ `01c7cf7d`:** اتعمل 2026-11-13 بـ rollout محروس: عامل واحد في المرة، وفحص صحة، والحاويات التانية بنفس الهوية، ورجوع تلقائي. الـ 18 عامل نجحوا.
- **عامل الفحص الأمني:**
  - المحاولة الأولى رجعت تلقائي، لأن الصورة المبنية اتغير مستخدمها لـ root.
  - المحاولة التانية رجعت المستخدم 1000:1000 ونجحت.

## الباقي في FR-25

- **FR-25C:** نشر صور الـ 3D، وده واقف على O-15.
- **FR-25D:** القبول الحي، وأدلة المستخدم والمالك والتشغيل. وبعدهم مراقبة الـ 72 ساعة النهائية (6.2).
