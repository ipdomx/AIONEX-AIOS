# مراجعة وتنظيف AIONEX AIOS — 2026-08-28

## النطاق

تمت مراجعة المستودع والخادم بهدف إزالة أي مسار تشغيل وهمي أو قديم ثبت عدم الحاجة إليه، مع الامتناع عن حذف أي دليل تشغيل أو rollback أو worktree غير محسوم.

- tracked files: 1,784
- ملفات نصية مفحوصة في المسح النهائي: 1,702
- أسطر نصية مفحوصة: 355,759
- Backend Zero-Dead: 726 ملف Python و575 API route، دون finding مانع.
- Phase31F repository certification: PASS.
- Repository security audit: PASS.
- tracked-secret / forbidden-pattern security audit: PASS.
- VIP portal integrity: 96 ملف، 6 لغات مكتملة، ولا simulated-data markers.
- Production DB fixture scan: 1,499 عمودًا نصيًا، دون demo/test/mock/fake/dummy/placeholder rows.
- Active production secret/env scan: 26 ملفًا، دون placeholder secret values.

## إزالة الـ mock من مسار الإنتاج

كان `OfflineMockExecutor` قابلًا للوصول من `ProjectPlanningRunner` قبل استدعاء OpenAI الحقيقي. أزيل هذا الاعتماد بالكامل بدل إعادة تسميته:

- حذف `src/aios/offline_execution.py` ومحرك OfflineMock بالكامل.
- Project Execution لا ينشئ `offline/` ولا يمرر offline evidence.
- Cloud comparison أصبح real-only بين retained local Qwen3:8b evidence وOpenAI execution evidence.
- Local Qwen sandbox أصبح ينتج local execution assessment مستقلًا، بلا synthetic baseline.
- إزالة `offline_mock_readiness` من واجهة الـVIP.
- تحديث Phase22D EvidenceClosure كي لا يعتمد على محرك mock المتقاعد.
- لا يوجد `OfflineMockExecutor` أو `offline-mock` runtime marker في current production source.

المحاكاة المعلنة صراحة مثل campaign pre-launch simulation لم تُعتبر mock runtime لأنها capability advisory متعمدة وموسومة بوضوح ولا تدعي spend أو provider execution حقيقيًا.

## إزالة subsystem قديم غير مستخدم

حزمة `payments_billing/` كانت subsystem تاريخيًا منفصلًا يحتوي `InMemoryBillingRepository` وعقود provider مجردة، ولا يستوردها أي Production code ولا تدخل packaging. نظام الفوترة الفعلي موجود في Backend production services ويدعم Stripe/PayPal/mobile stores/webhooks. لذلك أزيلت الحزمة القديمة واختبارها فقط.

## اختبارات ما بعد الإزالة

بعد الإزالة الجذرية للـmock والـlegacy billing:

- `PYTHONPATH=.:src pytest -q tests`: **849 passed**.
- الاختبارات المنخفضة من baseline السابق تخص فقط ملفات الاختبار التي حذفت مع subsystemين المتقاعدين، وليست failures أو skips.
- focused cloud/local/evidence tests: **83 passed**.
- `git diff --check`: PASS.
- changed Python compile: PASS.

## تنظيف الخادم

تم التنظيف فقط بعد إثبات أن المورد غير مستخدم أو قابل لإعادة البناء، مع حفظ manifest/evidence عند الحاجة:

- إزالة 112 Git worktree كانت clean وmerged بالكامل.
- إزالة worktree إضافي `feature/user-telegram-bot` بعد إثبات `git cherry` أنه patch-equivalent إلى `origin/main`.
- إبقاء كل worktree يحتوي commit فريدًا أو bytes محلية تختلف عن main.
- إزالة anonymous/dangling Docker volumes غير المرتبطة بأي container.
- إزالة 67 Docker tag من test/source-contract/candidate فقط بعد إثبات عدم استخدامها.
- عدم حذف dangling image الوحيدة لأنها مستخدمة فعليًا بواسطة containers حية.
- إزالة host `node_modules`, `.next`, pytest/mypy/compile caches غير mounted وقابلة لإعادة البناء.
- إزالة Trivy/Nuclei/tool caches المكررة، مع الاحتفاظ بالتقارير النهائية.
- الاحتفاظ بتقرير Security Acceptance النهائي PASS، SHA-256:
  `e742dcffd5399861130d8625bf15e69da11db8ad5e333ea277e0dfd5c770f25f`.
- إزالة tool-cache فقط من full-project audit القديم مع الاحتفاظ بتقارير file-by-file/security النهائية.
- تقليل system journal إلى أقل من 500MB مع الاحتفاظ بالسجلات الحديثة.
- تنظيف `/tmp` من diagnostics/build/test artifacts القديمة غير referenced وغير المفتوحة بواسطة processes.

انخفض استخدام القرص من قرابة 97% في بداية المراجعة إلى قرابة 63%، مع أكثر من 300GB متاحة.

## أشياء تم الحفاظ عليها عمدًا

لم تُحذف العناصر التالية لأنها ما زالت ذات قيمة أو لم يثبت أنها عديمة القيمة:

- أي unique/unmerged/dirty Git worktree.
- `/tmp/phase36d-runtime-closure` لأنه worktree فريد غير مدموج.
- `/tmp/adb.0.log` لأنه مفتوح من process حي.
- `studio-worker-rootfs-20260821T222357Z.tar.gz` لأن rollback evidence يعتمد على SHA الخاص به.
- rollback images الفريدة؛ لم تستخدم سياسة `docker prune -a` العمياء.
- الـLIVE feature gates غير المفعلة؛ هي activation boundaries حقيقية وليست mock outputs.
- أي external/funded/legal activation gate يحتاج صلاحية أو رصيدًا أو اعتمادًا خارجيًا.

## بوابة الإغلاق

لا تُعتبر هذه المراجعة production-complete إلا بعد مرور protected CI، دمج التغيير في `main`، تحديث صور الخدمات المتأثرة، وإعادة التحقق من Production runtime والصحة بعد النشر.
