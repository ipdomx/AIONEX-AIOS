# Phase 36N receipt — FR-03A3 Actions / Trivy timeout

مرجع المتابعة الموحد هو `docs/project/PROJECT-REPORT.md`. هذا الإيصال يثبت نطاق المصدر فقط.

تم إعداد تحديثي SBOM/Trivy كـfull SHA pins، مع زيادة مهلة Trivy لصورة TripoSR من الافتراضي الذي انتهى بعد خمس دقائق إلى `15m`. لا تخفيض في severity أو exit gate أو ignore-unfixed، ولا تعطيل للمسح.
