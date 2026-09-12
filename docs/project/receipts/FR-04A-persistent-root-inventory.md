# FR-04A — حصر الجذور الدائمة ومصفوفة تغطية النسخ

الحالة: **inventory complete — no production mutation**.

المصدر الحي عند الجرد: `c7baf7a1fcdca28d692172a8529c34840942fb15`. الجرد من mounts الفعلية للحاويات ومن أحجام volumes على المضيف، وليس من افتراضات الكود فقط.

## النتيجة

النسخ الحالي يغطي قاعدة البيانات منطقيًا عبر `pg_dump` ويضم مسار 3D snapshot فقط. `backup-worker` لا يركب بقية volumes الخاصة ببيانات المنصة، لذلك لا توجد تغطية حالية للوسائط ومخرجات المشاريع وStudio والدورات والتسجيلات وPortal وإصدارات mobile وsong ingress ومصادر/مخرجات Security.

الجذور الواجب إضافتها في FR-04B: `media_asset_data`, `project_execution_data`, `studio_asset_data`, `course_package_data`, `realtime_recording_data`, `portal_asset_data`, `mobile_release_data`, `audio_song_ingress_data`, `security_source_data`, `security_remediation_data`.

`redis_data` ليس مجهولًا: Redis يعمل AOF و`noeviction`، لذلك يمنع إسقاطه بصمت. FR-04C يجب أن يثبت إما استعادة متسقة له أو عقد إعادة بناء آمن من المصادر الدائمة.

المستبعد عمدًا من نسخ بيانات المستخدم: `project_npm_cache_data`, `security_tool_cache_data`, `ollama_model_data`, `postgres_socket`، بشرط إبقاء عقود إعادة البناء/الزوال واضحة. الأسرار منفصلة عن asset backup ولا يجوز جمعها عشوائيًا؛ معالجة مفاتيح/أسرار الاستعادة ضمن FR-05/06/24.

التفاصيل والأحجام/الأعداد الفعلية في `FR-04A-persistent-root-inventory.json`.
