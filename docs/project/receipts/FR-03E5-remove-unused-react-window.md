# FR-03E5 — إزالة react-window غير المستخدم

التاريخ: 2026-09-12

- تمت المراجعة فوق `main` بعد دمج FR-03E4 (`df1335faae8adb2d471d7b69361da1a86ab78d62`).
- لا توجد أي imports أو require أو مستهلكات لـ `react-window` في مصدر Frontend المتعقب؛ الظهور كان في package metadata فقط.
- أزيل `react-window` و `@types/react-window` بدل ترقية major إلى 2.x لا يستخدمها المنتج.
- أضيف contract test يمنع عودة الاعتماد المباشر ما لم يُدخل استخدام فعلي ومراجع.
- القبول المحلي: focused contract `2/2 PASS`، `npm audit` صفر ثغرات، Owner Arabic 1079 نصًا، TypeScript/API contracts PASS، ESLint PASS، بوابة Prettier المطابقة لـCI PASS، وNext production build PASS.
- لا نشر Frontend في هذا الجزء؛ النشر يجمع بعد اكتمال FR-03E.
