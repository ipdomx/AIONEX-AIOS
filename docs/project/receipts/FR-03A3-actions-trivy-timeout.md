# FR-03A3 — تحديث Actions ومعالجة مهلة TripoSR

- يستبدل SHA المثبت لـ `anchore/sbom-action` بالـSHA المعتمد الجديد في Phase34E وPhase34F.
- يستبدل SHA المثبت لـ `aquasecurity/trivy-action` بالـSHA المعتمد الجديد في Phase34E وPhase34F.
- لا يغير Trivy: يبقى `v0.72.0` و`CRITICAL,HIGH` و`ignore-unfixed: false` و`exit-code: 1`.
- بعد تشغيل PR576 ظهر فشل `context deadline exceeded` بعد 5 دقائق على صورة TripoSR الكبيرة، وليس finding أمنيًا. لذلك يضاف `timeout: 15m` لمسح TripoSR فقط دون تقليل scanners أو severity أو شروط الفشل.
- عقد المصدر يبقي full-length SHA pinning وقائمة الاعتماد المغلقة.
