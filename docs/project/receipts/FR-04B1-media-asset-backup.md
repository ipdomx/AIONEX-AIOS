# FR-04B1 — Media asset backup coverage

الحالة في هذا الإيصال: مرشح مصدر محلي، لا يثبت دمجًا أو نشرًا حيًا قبل الفحوص المحمية.

النطاق الصغير لهذه الدفعة هو `media_asset_data` فقط. لا تضيف هذه الدفعة project executions أو courses أو recordings أو portal/mobile/studio/security roots؛ تبقى لأجزاء FR-04B اللاحقة.

التغيير يضيف companion snapshot خاصًا بالوسائط إلى platform backup، مع manifest يحصي الملفات وحجم payload وبصمة SHA-256 لكل ملف، ويرفض symlinks والمسارات غير الآمنة والملفات ذات صلاحيات group/other. الـbackup-worker يركب volume الوسائط read-only، يحسب مساحة snapshot قبل البدء، ينظف partial/orphan artifacts مع retention، ويسجل durable `media_snapshot` evidence.

R2 يرفع `media-assets.tar` داخل نفس prefix للنسخة، يقرأه كاملًا بعد الرفع للتحقق من SHA-256 والحجم، ويضيفه إلى manifest الخارجي. restore validation يتطلب ويحقق companion المحلي والخارجي عندما تكون تغطية الوسائط مفعلة.

التحقق المحلي قبل PR: focused backup/database suite `72 passed, 1 skipped`؛ عقد FR-04B1 `2/2`؛ Ruff PASS؛ mypy PASS على الملفات المعدلة؛ Core root `980/980` PASS. الـskip الموجود سابق وليس تنازلاً جديدًا.
