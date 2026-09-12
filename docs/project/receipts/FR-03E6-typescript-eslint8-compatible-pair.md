# FR-03E6 — typescript-eslint 8 كزوج متوافق

التاريخ: 2026-09-12

- المراجعة فوق `main` بعد دمج FR-03E5 (`26d1999a04cdb2eebc43156d4b362511e675a15f`).
- PR578 القديم كان يرفع `@typescript-eslint/eslint-plugin` إلى 8.x ويترك `@typescript-eslint/parser` على 7.x؛ لذلك أُغلق كمسار غير متوافق.
- رُقي `@typescript-eslint/eslint-plugin` و`@typescript-eslint/parser` معًا إلى 8.70.0 مع إبقاء ESLint 8.57 وTypeScript 5.x ضمن peer ranges المدعومة.
- أضيف contract يمنع mixed-major بين plugin وparser.
- القبول المحلي: npm audit صفر ثغرات؛ Owner Arabic 1079؛ TypeScript/API contracts؛ Next lint؛ CI Prettier scope؛ Next production build — كلها PASS.
- لا نشر Frontend في هذا الجزء.
