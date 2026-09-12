# FR-03E7 — Frontend runtime compatible group

التاريخ: 2026-09-12

- هذا الجزء مبني فوق مرشح FR-03E6 المتوافق؛ لا يدعي دمج E6 قبل فحوصه المحمية.
- بعد Tailwind 4 لم يعد `autoprefixer` اعتمادًا مباشرًا، لذلك لم يُعد إدخاله من مجموعة Dependabot القديمة.
- التحديثات المتبقية فقط: `postcss` 8.5.28، `posthog-js` 1.428.8، `react-hook-form` 7.87.0.
- رُفع `postcss` المباشر و`overrides.postcss` معًا لمنع EOVERRIDE وعدم اتساق lockfile.
- القبول المحلي: npm audit صفر ثغرات؛ Owner Arabic 1079؛ TypeScript/API contracts؛ Next lint؛ CI Prettier scope؛ Next production build — كلها PASS.
- لا نشر Frontend في هذا الجزء.
