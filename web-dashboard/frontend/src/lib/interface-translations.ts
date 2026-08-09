import type { SupportedLocale } from "@/lib/locale-engine";

type Catalog = Record<string, string>;

const AR: Catalog = {
  "Loading owner 3D policy…": "جارٍ تحميل سياسة الأبعاد الثلاثية للمالك…",
  "3D access and GPU limits synchronized.":
    "تمت مزامنة صلاحيات الأبعاد الثلاثية وحدود وحدة معالجة الرسومات.",
  "3D policy could not be loaded.": "تعذر تحميل سياسة الأبعاد الثلاثية.",
  "Owner 3D policy saved and audit-logged.":
    "تم حفظ سياسة الأبعاد الثلاثية للمالك وتسجيلها في سجل التدقيق.",
  "3D policy update failed.": "فشل تحديث سياسة الأبعاد الثلاثية.",
  "Owner 3D Control": "تحكم المالك في الأبعاد الثلاثية",
  "3D Access, Spend & Recovery": "صلاحيات الأبعاد الثلاثية والتكلفة والاستعادة",
  "The highest public tier is the default eligibility boundary. The Super Owner can enable or suspend 3D, change eligible plans, grant or deny individual users, and set every GPU cost/recovery limit.":
    "أعلى باقة عامة هي حد الأهلية الافتراضي. يستطيع المالك الأعلى تشغيل خدمة الأبعاد الثلاثية أو إيقافها، وتغيير الباقات المؤهلة، والسماح أو الحظر لمستخدمين بعينهم، وضبط جميع حدود تكلفة واستعادة وحدة معالجة الرسومات.",
  "Save policy": "حفظ السياسة",
  "User eligibility": "أهلية المستخدم",
  "3D service enabled": "خدمة الأبعاد الثلاثية مفعلة",
  "Eligible plan codes": "رموز الباقات المؤهلة",
  "Required entitlement": "الاستحقاق المطلوب",
  "Explicitly allowed user IDs": "معرفات المستخدمين المسموح لهم صراحة",
  "Explicitly denied user IDs": "معرفات المستخدمين المحظورين صراحة",
  "Concurrent jobs / user": "المهام المتزامنة لكل مستخدم",
  "Max runtime seconds": "الحد الأقصى لثواني التشغيل",
  "Max queue seconds": "الحد الأقصى لثواني الانتظار",
  "Max retries": "الحد الأقصى لإعادة المحاولة",
  "Max job cost USD": "الحد الأقصى لتكلفة المهمة بالدولار",
  "Daily spend ceiling USD": "سقف الإنفاق اليومي بالدولار",
  "Monthly spend ceiling USD": "سقف الإنفاق الشهري بالدولار",
  "Owner alert threshold %": "نسبة حد تنبيه المالك",
  "GLB compression policy": "سياسة ضغط GLB",
  "Generation quota, image size, texture resolution, artifact retention and signed-link lifetime below are enforced server-side for every user.":
    "يتم فرض حصة الإنشاء وحجم الصورة ودقة الخامات ومدة الاحتفاظ بالملف وصلاحية الروابط الموقعة أدناه من الخادم على كل مستخدم.",
  "Monthly jobs / user": "المهام الشهرية لكل مستخدم",
  "Max input image MB": "الحد الأقصى لحجم صورة الإدخال بالميجابايت",
  "Max texture size": "الحد الأقصى لدقة الخامات",
  "Artifact retention days": "أيام الاحتفاظ بالملف",
  "Signed URL lifetime seconds": "مدة صلاحية الرابط الموقّع بالثواني",
  Compatibility: "توافق واسع",
  Meshopt: "ضغط Meshopt",
  "· commit": "· معرّف الالتزام",
  "Mobile Delivery": "تسليم تطبيقات الهاتف",
  "PWA, Android, iOS, signing boundaries, and release artifacts.":
    "تطبيق الويب التقدمي وأندرويد وiOS وحدود التوقيع وملفات الإصدار.",
  "Owner Mobile Delivery": "تسليم تطبيقات الهاتف للمالك",
  "PWA, Android & iOS Release Evidence":
    "أدلة إصدارات تطبيق الويب التقدمي وأندرويد وiOS",
  "Verified install, update, offline, signing, artifact, and publication boundaries. App-store publication and the final ai.vip-e.net upload remain explicit external actions and are never reported as completed.":
    "حدود موثقة للتثبيت والتحديث والعمل دون اتصال والتوقيع والملفات والنشر. يظل النشر في متاجر التطبيقات والرفع النهائي إلى ai.vip-e.net إجراءات خارجية صريحة ولا يتم الإبلاغ عنها كمكتملة.",
  "Loading mobile release evidence...": "جارٍ تحميل أدلة إصدارات الهاتف...",
  "Mobile release evidence synchronized.": "تمت مزامنة أدلة إصدارات الهاتف.",
  "Mobile release evidence could not be loaded.":
    "تعذر تحميل أدلة إصدارات الهاتف.",
  "Downloading protected mobile artifact...": "جارٍ تنزيل ملف الهاتف المحمي...",
  "Mobile artifact integrity was verified and the download started.":
    "تم التحقق من سلامة ملف الهاتف وبدأ التنزيل.",
  "Mobile artifact download failed integrity or access validation.":
    "فشل تنزيل ملف الهاتف بسبب التحقق من السلامة أو الوصول.",
  "No registered release": "لا يوجد إصدار مسجل",
  "Validations passed": "نجحت عمليات التحقق",
  "Validation unavailable": "التحقق غير متاح",
  "Download verified artifact": "تنزيل الملف الموثق",
  signed: "موقّع",
  "unsigned boundary": "حد غير موقّع",
  "not built": "لم يتم بناؤه",
  unavailable: "غير متاح",
  "Communication queues, receipts, and support records synchronized.":
    "تمت مزامنة قوائم انتظار الاتصالات وإيصالاتها وسجلات الدعم.",
  "Communication evidence could not be loaded.": "تعذر تحميل أدلة الاتصالات.",
  "Re-queueing the selected delivery…":
    "جارٍ إعادة التسليم المحدد إلى قائمة الانتظار…",
  "Delivery was safely returned to the durable queue.":
    "أُعيد التسليم بأمان إلى قائمة الانتظار الدائمة.",
  "Delivery retry failed.": "فشلت إعادة محاولة التسليم.",
  "Resolving the selected support request…": "جارٍ حل طلب الدعم المحدد…",
  "Support request resolved and retained in the audit trail.":
    "تم حل طلب الدعم والاحتفاظ به في سجل التدقيق.",
  "Support update failed.": "فشل تحديث الدعم.",
  "Notification, Delivery & Support Control":
    "التحكم في الإشعارات والتسليم والدعم",
  "Durable in-app records, truthful provider readiness, delivery receipts, retries, dead-letter recovery, and private support intake.":
    "سجلات دائمة داخل التطبيق، وجاهزية صادقة للمزودين، وإيصالات تسليم، وإعادة محاولات، واستعادة الرسائل المتعثرة، واستقبال دعم خاص.",
  "Truthful channel readiness": "جاهزية القنوات الفعلية",
  "Delivery receipts & recovery": "إيصالات التسليم والاستعادة",
  "Every external attempt remains durable, including unconfigured and dead-letter states.":
    "تظل كل محاولة خارجية محفوظة، بما فيها حالات عدم التهيئة والرسائل المتعثرة.",
  "No delivery records are available.": "لا توجد سجلات تسليم متاحة.",
  "Retry delivery": "إعادة محاولة التسليم",
  "Private support intake": "استقبال الدعم الخاص",
  "Requests remain tenant-owned while the Super Owner has complete platform visibility.":
    "تظل الطلبات مملوكة للمؤسسة مع رؤية كاملة للمالك الأعلى على المنصة.",
  "No support requests are recorded.": "لا توجد طلبات دعم مسجلة.",
  "Resolve request": "حل الطلب",
  "Councils, ministries, policies, and decisions synchronized.":
    "تمت مزامنة المجالس والوزارات والسياسات والقرارات.",
  "Governance records could not be loaded.": "تعذر تحميل سجلات الحوكمة.",
  "Councils, Ministries, Policies & Decisions":
    "المجالس والوزارات والسياسات والقرارات",
  "Durable governance bodies, weighted quorum, policy lifecycle, change requests, rejection, and final Owner ratification.":
    "هيئات حوكمة دائمة ونصاب موزون ودورة حياة للسياسات وطلبات تعديل ورفض وتصديق نهائي من المالك.",
  "Create council or ministry": "إنشاء مجلس أو وزارة",
  "Governance body name": "اسم هيئة الحوكمة",
  "No parent body": "لا توجد هيئة أم",
  "Charter and responsibilities": "الميثاق والمسؤوليات",
  "Create governance body": "إنشاء هيئة حوكمة",
  "· quorum": "· النصاب",
  "Create governed policy": "إنشاء سياسة محكومة",
  "Policy code": "رمز السياسة",
  "Policy title": "عنوان السياسة",
  "Organization-wide Owner policy": "سياسة المالك على مستوى المؤسسة",
  "Policy purpose and rules": "غرض السياسة وقواعدها",
  "Create policy": "إنشاء سياسة",
  "· version": "· الإصدار",
  "Submit for approval": "إرسال للموافقة",
  "Create governance decision": "إنشاء قرار حوكمة",
  "Direct Owner decision": "قرار مباشر من المالك",
  "No linked policy": "لا توجد سياسة مرتبطة",
  "Decision rationale and retained evidence": "مبررات القرار والأدلة المحفوظة",
  "Create decision": "إنشاء قرار",
  "Weighted body vote": "تصويت موزون للهيئة",
  "Direct Owner review": "مراجعة مباشرة من المالك",
  "Open review cycle": "فتح دورة المراجعة",
  "· escalation": "· التصعيد",
  "Access Authority": "سلطة الوصول",
  Active: "نشط",
  "Active roles": "الأدوار النشطة",
  "Active users": "المستخدمون النشطون",
  Administrator: "مسؤول النظام",
  Agents: "الوكلاء",
  "AI, cloud, source control, database, and channel integrations.":
    "تكاملات الذكاء الاصطناعي والسحابة والتحكم بالمصدر وقواعد البيانات والقنوات.",
  Alerts: "التنبيهات",
  All: "الكل",
  "All Status": "كل الحالات",
  "All Users": "كل المستخدمين",
  "API Keys": "مفاتيح API",
  "API keys & secret references": "مفاتيح API ومراجع الأسرار",
  Appearance: "المظهر",
  "Approval Center": "مركز الموافقات",
  "Approval Execution": "تنفيذ الموافقات",
  Approve: "موافقة",
  "Arabic dialect": "اللهجة العربية",
  Audience: "الجمهور",
  Audit: "التدقيق",
  Authenticated: "المستخدمون المسجلون",
  "Auto-refreshed backend metrics and owner audit-event visibility.":
    "مقاييس خلفية متجددة تلقائيًا ورؤية أحداث تدقيق المالك.",
  "Backups, restore validation, and disaster recovery drills.":
    "النسخ الاحتياطية والتحقق من الاستعادة وتدريبات التعافي من الكوارث.",
  Billing: "الفوترة",
  "Billing & Plans": "الفوترة والخطط",
  "Branding, theme, pages, pricing, assets, translations, publishing, and rollback.":
    "الهوية والتصميم والصفحات والأسعار والملفات والترجمات والنشر والرجوع للإصدارات.",
  "Budgets, limits, service usage, and suspension thresholds.":
    "الميزانيات والحدود واستخدام الخدمات وحدود الإيقاف.",
  "Change password": "تغيير كلمة المرور",
  "Changing password…": "جارٍ تغيير كلمة المرور…",
  "Close navigation": "إغلاق التنقل",
  "Close profile menu": "إغلاق قائمة الحساب",
  "Communication channels, routing, and delivery control.":
    "قنوات الاتصال والتوجيه والتحكم في التسليم.",
  Communications: "الاتصالات",
  Completed: "مكتمل",
  "Completion Inventory": "جرد الاكتمال",
  "Platform Completion Program": "برنامج إكمال المنصة",
  "Evidence-backed inventory of every AIOS module, Owner page, public portal page, backend endpoint, and completion batch. AI models and providers are deliberately reserved for the final batch.":
    "جرد قائم على الأدلة لكل وحدة في AIOS وصفحة للمالك وصفحة في البوابة العامة ونقطة نهاية خلفية ودفعة إكمال، مع حجز نماذج ومزودي الذكاء الاصطناعي للدفعة الأخيرة عمدًا.",
  "Refresh evidence": "تحديث الأدلة",
  "Runtime readiness": "جاهزية التشغيل",
  "Full platform completion": "اكتمال المنصة بالكامل",
  "Batches closed": "الدفعات المغلقة",
  "Current batch": "الدفعة الحالية",
  "No-omission completion contract": "عقد الإكمال دون إغفال",
  "verified of": "متحقق منها من أصل",
  "non-provider features.": "ميزة غير مرتبطة بالمزودين.",
  "provider/model feature is held for": "ميزة النماذج والمزودين مؤجلة إلى",
  ", the final batch.": "، وهي الدفعة الأخيرة.",
  "Completion batches": "دفعات الإكمال",
  "features verified": "ميزات متحقق منها",
  "Live release and dependency checks": "فحوص الإصدار والاعتمادات المباشرة",
  Compliance: "الامتثال",
  "Compliance Runtime": "تشغيل الامتثال",
  "Confirm new password": "تأكيد كلمة المرور الجديدة",
  "Confirm password": "تأكيد كلمة المرور",
  Containers: "الحاويات",
  Copy: "نسخ",
  "Cost Governance": "حوكمة التكاليف",
  "Country code (required)": "رمز الدولة (مطلوب)",
  Create: "إنشاء",
  "Create a free account": "إنشاء حساب مجاني",
  "Create free account": "إنشاء الحساب المجاني",
  "Create Project": "إنشاء المشروع",
  "Create project": "إنشاء مشروع",
  Creating: "جارٍ الإنشاء",
  Critical: "حرج",
  Currency: "العملة",
  "Current password": "كلمة المرور الحالية",
  "Current password is incorrect": "كلمة المرور الحالية غير صحيحة",
  Dark: "داكن",
  Dashboard: "لوحة التحكم",
  Database: "قاعدة البيانات",
  "Database health": "صحة قاعدة البيانات",
  Databases: "قواعد البيانات",
  "Date of birth": "تاريخ الميلاد",
  Delete: "حذف",
  "Delivery rules for in-app, email, push, and WhatsApp.":
    "قواعد التسليم داخل التطبيق والبريد والدفع وواتساب.",
  "Dependency health, alert, backup, and recovery readiness.":
    "صحة الاعتمادات والتنبيهات والنسخ الاحتياطي وجاهزية الاستعادة.",
  Description: "الوصف",
  Developer: "مطور",
  Disabled: "معطلة",
  "Durable owner decision records and approval state.":
    "سجلات دائمة لقرارات المالك وحالة الموافقة.",
  Email: "البريد الإلكتروني",
  "Email notifications": "إشعارات البريد الإلكتروني",
  "Enable, suspend, and govern platform services.":
    "تفعيل خدمات المنصة وإيقافها وحوكمتها.",
  Enabled: "مفعلة",
  Engineer: "مهندس",
  English: "الإنجليزية",
  "Entity Operations": "عمليات الكيانات",
  Events: "الأحداث",
  "Executive Intelligence": "الذكاء التنفيذي",
  "Executive Overview": "النظرة التنفيذية",
  Favorites: "المفضلة",
  "Final Integration": "التكامل النهائي",
  "Final quality, security, performance, and owner gates.":
    "بوابات الجودة والأمان والأداء والمالك النهائية.",
  "Framework controls, evidence, risk, and assurance.":
    "ضوابط الأطر والأدلة والمخاطر والتأكيد.",
  "Free User": "مستخدم مجاني",
  "Free user registration": "تسجيل مستخدم مجاني",
  "Full name": "الاسم الكامل",
  "Full owner capability and navigation completion check.":
    "فحص اكتمال قدرات المالك ومسارات التنقل.",
  Global: "عام",
  "Global Command": "القيادة العامة",
  "Global policy scope, enforcement, and lifecycle.":
    "نطاق السياسات العامة وإنفاذها ودورة حياتها.",
  "Global Search": "البحث الشامل",
  "Global Timeline": "الخط الزمني العام",
  "Govern and review every project from one center.":
    "إدارة ومراجعة كل مشروع من مركز واحد.",
  Guests: "الزوار",
  High: "مرتفع",
  "Identity, secrets, threat defense, and compliance health.":
    "الهوية والأسرار والدفاع ضد التهديدات وصحة الامتثال.",
  "Incident Command": "قيادة الحوادث",
  Infrastructure: "البنية التحتية",
  "Integration, security, performance, reliability, and usability checks.":
    "فحوص التكامل والأمان والأداء والموثوقية وسهولة الاستخدام.",
  "Integrations Registry": "سجل التكاملات",
  "Interface language": "لغة الواجهة",
  "Internal staff identity, role, organization, and status.":
    "هوية الموظفين الداخليين وأدوارهم ومؤسساتهم وحالتهم.",
  Knowledge: "المعرفة",
  Language: "اللغة",
  "Language & Region": "اللغة والمنطقة",
  "Language and voice controls": "أدوات اللغة والصوت",
  "Latest backend-reported dependency nodes and health.":
    "أحدث عقد الاعتماد وحالتها كما يعلنها الخادم.",
  Licensing: "التراخيص",
  Light: "فاتح",
  "Live backend dependency and non-owner release-gate readiness.":
    "جاهزية اعتماد الخادم وبوابات الإصدار غير التابعة للمالك.",
  "Live backend dependency health and configured origins.":
    "صحة اعتمادات الخادم المباشرة والمصادر المضبوطة.",
  "Live compliance controls and owner attestations.":
    "ضوابط امتثال مباشرة وإقرارات المالك.",
  "Live Ownership Data": "بيانات الملكية المباشرة",
  "Loading live access roles…": "جارٍ تحميل الأدوار المباشرة…",
  "Loading live billing accounts…": "جارٍ تحميل حسابات الفوترة…",
  "Loading live communication channels…": "جارٍ تحميل قنوات الاتصال…",
  "Loading live compliance controls…": "جارٍ تحميل ضوابط الامتثال…",
  "Loading live cost controls…": "جارٍ تحميل ضوابط التكاليف…",
  "Loading live governance records…": "جارٍ تحميل سجلات الحوكمة…",
  "Loading live incidents…": "جارٍ تحميل الحوادث…",
  "Loading live integrations…": "جارٍ تحميل التكاملات…",
  "Loading live notifications…": "جارٍ تحميل الإشعارات…",
  "Loading live organizations…": "جارٍ تحميل المؤسسات…",
  "Loading live owner services…": "جارٍ تحميل خدمات المالك…",
  "Loading live policies…": "جارٍ تحميل السياسات…",
  "Loading live projects…": "جارٍ تحميل المشروعات…",
  "Loading projects...": "جارٍ تحميل المشروعات...",
  "Loading settings...": "جارٍ تحميل الإعدادات...",
  Logout: "تسجيل الخروج",
  Logs: "السجلات",
  Low: "منخفض",
  "Manage organization plans and suspension state.":
    "أدر خطط المؤسسات وحالة الإيقاف.",
  "Manage protected external vault references.":
    "أدر مراجع الخزائن الخارجية المحمية.",
  Manager: "مدير",
  "Masked credentials, rotation, revocation, and scope.":
    "بيانات اعتماد مخفية وتدويرها وإلغاؤها ونطاقها.",
  Medium: "متوسط",
  Meetings: "الاجتماعات",
  Member: "عضو",
  Members: "الأعضاء",
  Metrics: "المقاييس",
  "MFA is configured at deployment level. Sign-in enforcement is reported separately by the authentication service.":
    "يتم ضبط المصادقة متعددة العوامل على مستوى النشر، ويعرض نظام الهوية حالة فرضها عند تسجيل الدخول بصورة مستقلة.",
  "MFA policy": "سياسة المصادقة متعددة العوامل",
  "Mobile number": "رقم الهاتف",
  "Mobile verification": "التحقق من الهاتف",
  Models: "النماذج",
  Monitoring: "المراقبة",
  Name: "الاسم",
  Navigation: "التنقل",
  "New password": "كلمة المرور الجديدة",
  "New password must differ from the current password":
    "يجب أن تختلف كلمة المرور الجديدة عن الحالية",
  "New passwords do not match.": "كلمتا المرور الجديدتان غير متطابقتين.",
  "New Project": "مشروع جديد",
  "No audit events match the current filters.":
    "لا توجد أحداث تدقيق تطابق المرشحات الحالية.",
  "No incidents are currently recorded.": "لا توجد حوادث مسجلة حاليًا.",
  "No index": "منع الفهرسة",
  "No integrations match the selected filters.":
    "لا توجد تكاملات تطابق المرشحات المحددة.",
  "No notifications match this filter.": "لا توجد إشعارات تطابق هذا المرشح.",
  "No organizations match the current search.":
    "لا توجد مؤسسات تطابق البحث الحالي.",
  "No other active sessions": "لا توجد جلسات أخرى نشطة",
  "No policies match the selected filters.":
    "لا توجد سياسات تطابق المرشحات المحددة.",
  "No projects match the current search.":
    "لا توجد مشروعات تطابق البحث الحالي.",
  "No staff records match the current filters.":
    "لا توجد سجلات موظفين تطابق المرشحات الحالية.",
  "No topology nodes match the selected region.":
    "لا توجد عقد بنية تطابق المنطقة المحددة.",
  "Notification Runtime": "تشغيل الإشعارات",
  Notifications: "الإشعارات",
  Open: "فتح",
  "Open command palette": "فتح لوحة الأوامر",
  "Open control": "فتح التحكم",
  "Open live PostgreSQL and dependency probes.":
    "افتح فحوص PostgreSQL والاعتمادات المباشرة.",
  "Open navigation": "فتح التنقل",
  "Operational and security incident coordination.":
    "تنسيق الحوادث التشغيلية والأمنية.",
  "Operational inventory, availability, and incident intelligence.":
    "مخزون التشغيل والتوافر وذكاء الحوادث.",
  "Operations Integration": "تكامل العمليات",
  "Orchestration, workers, memory, providers, and notifications.":
    "التنسيق والعمال والذاكرة والمزودون والإشعارات.",
  Organization: "المؤسسة",
  "Organization plan, seat, and access-status controls.":
    "التحكم في خطة المؤسسة والمقاعد وحالة الوصول.",
  "Organization plan, seat, suspension, and restore status.":
    "حالة خطط المؤسسات والمقاعد والإيقاف والاستعادة.",
  "Organization plans, boundaries, access, and status.":
    "خطط المؤسسات وحدودها وصلاحياتها وحالتها.",
  Organizations: "المؤسسات",
  "Organizations represented": "المؤسسات الظاهرة",
  "Other sessions signed out.": "تم تسجيل الخروج من الجلسات الأخرى.",
  Overview: "نظرة عامة",
  Owner: "مالك",
  "Owner / member sign in": "دخول المالك أو العضو",
  "Owner access": "وصول المالك",
  "Owner Access Authority": "سلطة وصول المالك",
  "Owner Approval Engine": "محرك موافقات المالك",
  "Owner Audit": "تدقيق المالك",
  "Owner Audit Command": "قيادة تدقيق المالك",
  "Owner Billing Authority": "سلطة فوترة المالك",
  "Owner Center": "مركز المالك",
  "Owner Communications": "اتصالات المالك",
  "Owner Compliance Center": "مركز امتثال المالك",
  "Owner Compliance Runtime": "تشغيل امتثال المالك",
  "Owner Control": "تحكم المالك",
  "Owner Cost Governance": "حوكمة تكاليف المالك",
  "Owner Dashboard Completion": "اكتمال لوحة المالك",
  "Owner Dashboard Finalization": "إنهاء لوحة المالك",
  "Owner Decisions": "قرارات المالك",
  "Owner decisions, staff actions, policies, and approvals.":
    "قرارات المالك وإجراءات الموظفين والسياسات والموافقات.",
  "Owner Executive Overview": "النظرة التنفيذية للمالك",
  "Owner Global Command": "القيادة العامة للمالك",
  "Owner Governance": "حوكمة المالك",
  "Owner identity, roles, permissions, and suspensions.":
    "هوية المالك والأدوار والصلاحيات والإيقافات.",
  "Owner Incident Command": "قيادة حوادث المالك",
  "Owner Integration Registry": "سجل تكاملات المالك",
  "Owner Licensing": "تراخيص المالك",
  "Owner Notification Registry": "سجل إشعارات المالك",
  "Owner only": "المالك فقط",
  "Owner Operations Integration": "تكامل عمليات المالك",
  "Owner Organization Command": "قيادة مؤسسات المالك",
  "Owner Policy Registry": "سجل سياسات المالك",
  "Owner Project Command": "قيادة مشروعات المالك",
  "Owner Recovery & Release": "الاستعادة والإصدارات",
  "Owner Recovery Center": "مركز استعادة المالك",
  "Owner Release Authority": "سلطة إصدار المالك",
  "Owner Release Governance": "حوكمة إصدارات المالك",
  "Owner Runtime": "تشغيل المالك",
  "Owner Secrets & Keys": "أسرار ومفاتيح المالك",
  "Owner Security Integration": "تكامل أمان المالك",
  "Owner Service Control": "تحكم المالك في الخدمات",
  "Owner Services & Security": "خدمات وأمن المالك",
  "Owner Staff Oversight": "إشراف المالك على الموظفين",
  "Owner Workforce Oversight": "إشراف المالك على القوى العاملة",
  "Human & Digital Workforce": "القوى العاملة البشرية والرقمية",
  "Live identity status plus evidence-based performance, health, training, supervision and certification for AIOS digital workers.":
    "حالة الهوية المباشرة مع الأداء والصحة والتدريب والإشراف والاعتماد القائم على الأدلة للعاملين الرقميين في AIOS.",
  "Human Staff": "الموظفون البشريون",
  "Digital Workers": "العاملون الرقميون",
  "Under Supervision": "تحت الإشراف",
  "In Retraining": "قيد إعادة التدريب",
  "Search worker, role, department, ministry or organization...":
    "ابحث بالعامل أو الدور أو القسم أو الوزارة أو المؤسسة...",
  "All Workforce": "كل القوى العاملة",
  "Loading workforce records...": "جارٍ تحميل سجلات القوى العاملة...",
  "No workforce records match the current filters.":
    "لا توجد سجلات قوى عاملة تطابق عوامل التصفية الحالية.",
  "Performance record": "سجل الأداء",
  "Successful assignments:": "المهام الناجحة:",
  "Failed or returned:": "المهام الفاشلة أو المعادة:",
  "Latest training assessment": "أحدث تقييم تدريبي",
  "Not passed": "لم يجتز",
  "No assessment recorded.": "لم يُسجل أي تقييم.",
  "Institute recommendation": "توصية المعهد",
  "Human account status is read directly from the identity database. Digital-worker performance scores do not apply to human identities.":
    "تُقرأ حالة الحساب البشري مباشرة من قاعدة بيانات الهوية، ولا تنطبق درجات أداء العاملين الرقميين على الهويات البشرية.",
  "Owner System Health": "صحة نظام المالك",
  "Owner System Map": "خريطة نظام المالك",
  "Owner-only authority over role status, access scope, privileged sessions and identity governance.":
    "سلطة خاصة بالمالك على حالة الأدوار ونطاق الوصول والجلسات المميزة وحوكمة الهوية.",
  "Owner-only control": "تحكم خاص بالمالك",
  "Owner-wide visibility into projects, approvals, incidents, staff, users and infrastructure.":
    "رؤية شاملة للمالك للمشروعات والموافقات والحوادث والموظفين والمستخدمين والبنية التحتية.",
  Password: "كلمة المرور",
  "Password changed successfully; active refresh sessions were revoked":
    "تم تغيير كلمة المرور بنجاح وتسجيل الخروج من الجلسات الأخرى.",
  Pause: "إيقاف مؤقت",
  Paused: "متوقف مؤقتًا",
  "Pending meeting requests requiring an owner decision.":
    "طلبات الاجتماعات المعلقة التي تتطلب قرار المالك.",
  Permissions: "الصلاحيات",
  Pill: "كبسولة",
  Plan: "الخطة",
  Planning: "تخطيط",
  "Platform Control": "تحكم المنصة",
  "Platform Integration": "تكامل المنصة",
  "Platform readiness, dependencies, and operational health.":
    "جاهزية المنصة والاعتمادات والصحة التشغيلية.",
  "Platform-wide operational commands and risk visibility.":
    "أوامر تشغيل على مستوى المنصة ورؤية شاملة للمخاطر.",
  Policies: "السياسات",
  "Policy Engine": "محرك السياسات",
  Price: "السعر",
  Priority: "الأولوية",
  "Production Finalization": "إنهاء الإنتاج",
  "Production Runtime": "تشغيل الإنتاج",
  "Production Studio": "استوديو الإنتاج",
  Profile: "الملف الشخصي",
  Progress: "التقدم",
  "Project Command": "قيادة المشروعات",
  "Project name": "اسم المشروع",
  Projects: "المشروعات",
  "Projects, organizations, and users across the platform.":
    "المشروعات والمؤسسات والمستخدمون عبر المنصة.",
  Protected: "محمي",
  "Protected accounts": "الحسابات المحمية",
  "Protected meeting approve, reject, and request-changes workflow.":
    "مسار محمي للموافقة على الاجتماعات أو رفضها أو طلب التعديل.",
  "Protected project, organization, and user operations.":
    "عمليات محمية للمشروعات والمؤسسات والمستخدمين.",
  Providers: "المزودون",
  Publish: "نشر",
  "Push notifications": "الإشعارات الفورية",
  Queues: "قوائم الانتظار",
  "Read selected text aloud": "قراءة النص المحدد بصوت مرتفع",
  "Realtime Monitoring": "المراقبة المباشرة",
  "Recovery Center": "مركز الاستعادة",
  Refresh: "تحديث",
  Reject: "رفض",
  "Release Authority": "سلطة الإصدار",
  "Release candidates, quality gates, and owner decisions.":
    "مرشحو الإصدار وبوابات الجودة وقرارات المالك.",
  "Release Governance": "حوكمة الإصدارات",
  Reports: "التقارير",
  "Request failed": "فشل الطلب",
  "Required privacy and security consent":
    "الموافقة المطلوبة على الخصوصية والأمان",
  "Reset draft to defaults": "إعادة المسودة للوضع الافتراضي",
  Restore: "استعادة",
  Resume: "استئناف",
  Risk: "المخاطر",
  Role: "الدور",
  "Role assignments": "تعيينات الأدوار",
  "Role Authority Matrix": "مصفوفة صلاحيات الأدوار",
  "Role records": "سجلات الأدوار",
  Roles: "الأدوار",
  "Roles, Permissions & Session Control":
    "الأدوار والصلاحيات والتحكم في الجلسات",
  Rounded: "مستدير",
  "Save changes": "حفظ التغييرات",
  "Save draft": "حفظ المسودة",
  Scope: "النطاق",
  "Scope:": "النطاق:",
  Search: "بحث",
  "Search owner-visible projects, services, policies, and records.":
    "ابحث في المشروعات والخدمات والسياسات والسجلات المتاحة للمالك.",
  "Search pages": "بحث الصفحات",
  "Search pages and Owner modules…": "ابحث في الصفحات ووحدات المالك…",
  "Search projects...": "البحث في المشروعات...",
  "Search roles...": "ابحث في الأدوار...",
  Seats: "المقاعد",
  "Secrets & Keys": "الأسرار والمفاتيح",
  Security: "الأمان",
  "Security Integration": "تكامل الأمان",
  "Select a workspace": "اختر مساحة عمل",
  "Select text, then press to read it aloud":
    "حدد نصًا ثم اضغط لقراءته بصوت مرتفع",
  "Send code": "إرسال الرمز",
  Servers: "الخوادم",
  "Service Control": "التحكم في الخدمات",
  Sessions: "الجلسات",
  Settings: "الإعدادات",
  "Settings synchronized.": "تمت مزامنة الإعدادات.",
  "Sign in": "تسجيل الدخول",
  "Sign out": "تسجيل الخروج",
  "Sign out other sessions": "تسجيل الخروج من الجلسات الأخرى",
  "Signed-in user": "المستخدم المسجل",
  "Signing out other sessions…": "جارٍ تسجيل الخروج من الجلسات الأخرى…",
  Square: "مربع",
  "Staff Oversight": "الإشراف على الموظفين",
  Status: "الحالة",
  "Stop reading aloud": "إيقاف القراءة الصوتية",
  "Strategic platform status, risks, readiness, and decisions.":
    "حالة المنصة الاستراتيجية والمخاطر والجاهزية والقرارات.",
  "Super Owner": "المالك الأعلى",
  "Super Owner Command Center": "مركز قيادة المالك الأعلى",
  Support: "الدعم",
  Suspend: "إيقاف",
  "Suspend or restore roles without affecting the protected owner account.":
    "أوقف الأدوار أو استعدها دون التأثير على حساب المالك المحمي.",
  Suspended: "موقوف",
  System: "النظام",
  "System Health": "صحة النظام",
  "System Topology": "بنية النظام",
  Tasks: "المهام",
  Teams: "الفرق",
  "The production dashboard currently uses its supported dark theme.":
    "تستخدم لوحة الإنتاج حاليًا النمط الداكن المدعوم.",
  "This session remains active until the next authenticated request after a password change.":
    "تظل هذه الجلسة ظاهرة حتى أول طلب موثق بعد تغيير كلمة المرور.",
  "Threat Center": "مركز التهديدات",
  Timezone: "المنطقة الزمنية",
  "Unified owner activity across platform domains.":
    "نشاط موحد للمالك عبر مجالات المنصة.",
  Update: "تحديث",
  "Updating…": "جارٍ التحديث…",
  Usage: "الاستخدام",
  User: "مستخدم",
  Username: "اسم المستخدم",
  Users: "المستخدمون",
  users: "مستخدمون",
  Validate: "تحقق",
  Verify: "تحقق",
  "VIP Portal Control": "التحكم في بوابة VIP",
  Visible: "ظاهر",
  "Voice input is inserted into the focused field":
    "يتم إدخال الصوت في الحقل المحدد",
  Workflows: "مسارات العمل",
  "— Unsaved changes.": "— توجد تغييرات غير محفوظة.",
  ", or": "، أو",
  ". Release decisions are locked.": ". قرارات الإصدار مقفلة.",
  "· Declared mode:": "· الوضع المعلن:",
  "· Evidence:": "· الدليل:",
  "· Health": "· الصحة",
  "· Last rotated": "· آخر تدوير",
  "· Owner team:": "· فريق المالك:",
  "· Owner:": "· المالك:",
  "· Readiness": "· الجاهزية",
  "· requested by": "· طُلب بواسطة",
  "· Requested by": "· طُلب بواسطة",
  "· Requested:": "· وقت الطلب:",
  "· Score": "· النتيجة",
  "· Target:": "· الهدف:",
  "(legacy — choose a supported plan)": "(قديم — اختر خطة مدعومة)",
  "% trend": "٪ اتجاه",
  "+ Add feature": "+ إضافة ميزة",
  "+ Add subscription period": "+ إضافة مدة اشتراك",
  "12+ characters": "12 حرفًا على الأقل",
  "A name with at least two characters is required.":
    "يلزم اسم مكوّن من حرفين على الأقل.",
  "Accepted: PNG, JPEG, WebP, ICO, sanitized SVG, WOFF2. Files are stored outside Git and served through the public API.":
    "المقبول: PNG وJPEG وWebP وICO وSVG المنقّى وWOFF2. تُحفظ الملفات خارج Git وتُعرض عبر الواجهة البرمجية العامة.",
  "Account status is read directly from the identity database.":
    "تُقرأ حالة الحساب مباشرة من قاعدة بيانات الهوية.",
  "Acknowledge critical alerts": "تأكيد الاطلاع على التنبيهات الحرجة",
  "Acknowledge the current critical threat alerts as the Super Owner?":
    "هل تريد تأكيد الاطلاع على تنبيهات التهديدات الحرجة الحالية بصفتك المالك الأعلى؟",
  "Active channels": "القنوات النشطة",
  "Active incidents": "الحوادث النشطة",
  "Active licenses": "التراخيص النشطة",
  "Active plans": "الخطط النشطة",
  "Active projects": "المشروعات النشطة",
  "Active seats": "المقاعد النشطة",
  "Active Staff": "الموظفون النشطون",
  "Add external reference": "إضافة مرجع خارجي",
  "Add navigation item": "إضافة عنصر تنقل",
  "Add plan": "إضافة خطة",
  "Advanced & History": "الإعدادات المتقدمة والسجل",
  "Advanced JSON applied locally. Save draft to validate it.":
    "طُبّق JSON المتقدم محليًا. احفظ المسودة للتحقق منه.",
  "AI Providers": "مزودو الذكاء الاصطناعي",
  "AI Runtime": "تشغيل الذكاء الاصطناعي",
  "AIONEX AIOS Owner Dashboard": "لوحة مالك AIONEX AIOS",
  "All categories": "كل الفئات",
  "All entities": "كل الكيانات",
  "All frameworks": "كل الأطر",
  "All Owner groups": "كل مجموعات المالك",
  "All reported regions": "كل المناطق المبلّغ عنها",
  "All scopes": "كل النطاقات",
  "All severity": "كل درجات الخطورة",
  "Allowed by owner": "مسموح به من المالك",
  "Announcement bar": "شريط الإعلانات",
  "API origin:": "مصدر API:",
  "Apply JSON locally": "تطبيق JSON محليًا",
  "Approval backend contract is not available.": "عقد خادم الموافقات غير متاح.",
  "Approval decision failed and was not persisted.":
    "فشل قرار الموافقة ولم يُحفظ.",
  "Approve release": "اعتماد الإصدار",
  "Approve Release": "اعتماد الإصدار",
  "Approve this release after all live validation gates have passed?":
    "هل تريد اعتماد هذا الإصدار بعد اجتياز جميع بوابات التحقق المباشرة؟",
  "Approved monthly limit:": "الحد الشهري المعتمد:",
  "Asset Library": "مكتبة الملفات",
  "Attest compliant": "إقرار الامتثال",
  "Attest control": "إقرار الضابط",
  "Attestation failed and was not persisted.": "فشل الإقرار ولم يُحفظ.",
  "Authenticated create, update, suspend, restore and delete requests for owner-managed records. No local-only success is reported when the backend contract is unavailable.":
    "طلبات موثقة لإنشاء سجلات المالك وتحديثها وإيقافها واستعادتها وحذفها. لا يُعرض نجاح محلي وهمي عند غياب عقد الخادم.",
  "Authenticated runtime view for projects, organizations and users across the platform.":
    "عرض تشغيل موثّق للمشروعات والمؤسسات والمستخدمين عبر المنصة.",
  "Auto-refresh failed; the last successful snapshot remains visible.":
    "فشل التحديث التلقائي؛ تظل آخر لقطة ناجحة ظاهرة.",
  "Auto-refresh is active every 15 seconds.":
    "التحديث التلقائي يعمل كل 15 ثانية.",
  "Auto-Refreshed Owner Monitoring": "مراقبة المالك بالتحديث التلقائي",
  "Awaiting readiness data": "في انتظار بيانات الجاهزية",
  "Back to Owner Center": "العودة إلى مركز المالك",
  "Backend Dependency Readiness": "جاهزية اعتمادات الخادم",
  "Backend Dependency Topology": "بنية اعتمادات الخادم",
  "Backend metric samples and owner audit events refreshed every 15 seconds.":
    "تُحدّث عينات مقاييس الخادم وأحداث تدقيق المالك كل 15 ثانية.",
  "Backup evidence": "دليل النسخ الاحتياطي",
  "Backup, Restore & Disaster Recovery":
    "النسخ الاحتياطي والاستعادة والتعافي من الكوارث",
  "Billing & plans": "الفوترة والخطط",
  "Blocked by owner": "محظور بواسطة المالك",
  "Brand, colors, fonts, logos, icons, navigation, all translated text overrides, pages, SEO, plans, subscription periods, pricing, visibility, assets, drafts, publishing, and rollback.":
    "الهوية والألوان والخطوط والشعارات والأيقونات والتنقل وتجاوزات النصوص المترجمة والصفحات وتحسين الظهور والخطط ومدد الاشتراك والأسعار والظهور والملفات والمسودات والنشر والرجوع.",
  "Central live health verification for the AIONEX AIOS control plane.":
    "تحقق مركزي مباشر من صحة طبقة التحكم في AIONEX AIOS.",
  "Complete ai.vip-e.net Control Center": "مركز التحكم الكامل في ai.vip-e.net",
  "Complete configuration JSON": "JSON الكامل للإعدادات",
  "Complete validation gates": "استكمال بوابات التحقق",
  "Compliance & Assurance": "الامتثال والتأكيد",
  "Compliance backend contract is not available.":
    "عقد خادم الامتثال غير متاح.",
  "Compliance Controls & Evidence": "ضوابط الامتثال والأدلة",
  "Compliance controls synchronized.": "تمت مزامنة ضوابط الامتثال.",
  "Configure integration": "إعداد التكامل",
  "Contact details": "بيانات التواصل",
  "Contact, Footer & Notice": "التواصل والتذييل والتنبيه",
  "Context for the owner decision": "سياق قرار المالك",
  "Control organization plan assignment, view seat use, and suspend or restore organization access.":
    "تحكم في تعيين خطط المؤسسات واعرض استخدام المقاعد وأوقف وصول المؤسسة أو استعده.",
  "Core integration": "تكامل أساسي",
  "Core platform access": "الوصول الأساسي للمنصة",
  "Core service": "خدمة أساسية",
  "Cost, Usage & Service Limits": "التكاليف والاستخدام وحدود الخدمات",
  "Create draft policy": "إنشاء سياسة كمسودة",
  "Create durable owner decision records and persist their approval or rejection state.":
    "أنشئ سجلات دائمة لقرارات المالك واحفظ حالة الموافقة أو الرفض.",
  "Create governed project": "إنشاء مشروع محكوم",
  "Create owner policy": "إنشاء سياسة للمالك",
  "Create, approve, pause and audit durable governance declarations. Automated enforcement applies only in consumers that explicitly integrate the recorded policy.":
    "أنشئ إعلانات حوكمة دائمة واعتمدها وأوقفها مؤقتًا ودققها. لا يطبق الإنفاذ الآلي إلا في المكونات التي تدمج السياسة المسجلة صراحةً.",
  "Credentials required": "بيانات اعتماد مطلوبة",
  "Critical events": "الأحداث الحرجة",
  "Critical incidents": "الحوادث الحرجة",
  "Critical open": "الحرجة المفتوحة",
  "Current request": "الطلب الحالي",
  "Decision intelligence": "ذكاء القرار",
  "Decision owner or body": "مالك القرار أو الجهة",
  "Decision title": "عنوان القرار",
  "Delete failed": "فشل الحذف",
  "Delete this unused asset?": "هل تريد حذف هذا الملف غير المستخدم؟",
  "Delivery policy": "سياسة التسليم",
  "Dependency and gate readiness": "جاهزية الاعتمادات والبوابات",
  "Deploy only when the live checks above reach 100% and CodeQL and Final Validation succeed. A completed backup, current performance evidence, security clearance, and explicit Owner approval are all required.":
    "لا تنشر إلا عندما تصل الفحوص المباشرة أعلاه إلى 100٪ وينجح CodeQL والتحقق النهائي. يلزم أيضًا نسخ احتياطي مكتمل ودليل أداء حديث وتصريح أمني وموافقة صريحة من المالك.",
  "Draft reset to defaults.": "أُعيدت المسودة إلى الإعدادات الافتراضية.",
  "Draft save failed.": "فشل حفظ المسودة.",
  "Draft saved. Public portal is unchanged until Publish.":
    "تم حفظ المسودة. لن تتغير البوابة العامة حتى الضغط على نشر.",
  "Durable owner decisions with explicit approval and rejection state.":
    "قرارات مالك دائمة بحالة موافقة أو رفض صريحة.",
  "Editing language:": "لغة التحرير:",
  "Enterprise Command Summary": "ملخص قيادة المؤسسة",
  "Enterprise operations synchronized.": "تمت مزامنة عمليات المؤسسة.",
  "Enterprise signals": "إشارات المؤسسة",
  "Every meeting decision is recorded in the owner audit trail.":
    "يُسجل كل قرار اجتماع في سجل تدقيق المالك.",
  "Evidence reference for": "مرجع الدليل لـ",
  "Evidence reference recorded and controls reloaded.":
    "تم تسجيل مرجع الدليل وإعادة تحميل الضوابط.",
  "Evidence reference was not recorded.": "لم يتم تسجيل مرجع الدليل.",
  "Evidence reference, URL, ticket, or artifact ID":
    "مرجع الدليل أو الرابط أو التذكرة أو معرّف الملف",
  "Evidence required": "الدليل مطلوب",
  "Evidence-backed Owner attestations for ISO 27001, SOC 2, GDPR and internal governance frameworks.":
    "إقرارات مالك مدعومة بالأدلة لأطر ISO 27001 وSOC 2 وGDPR والحوكمة الداخلية.",
  "Execute operation": "تنفيذ العملية",
  "Execute owner-level controls across projects, organizations and platform services.":
    "نفّذ ضوابط على مستوى المالك عبر المشروعات والمؤسسات وخدمات المنصة.",
  "Executing protected owner operation...": "جارٍ تنفيذ عملية مالك محمية...",
  "Executive intelligence backend contract is not available.":
    "عقد خادم الذكاء التنفيذي غير متاح.",
  "Executive Intelligence Center": "مركز الذكاء التنفيذي",
  "External reference": "مرجع خارجي",
  "External Secret References": "مراجع الأسرار الخارجية",
  "External Services & Providers": "الخدمات والمزودون الخارجيون",
  "Features —": "المزايا —",
  "Final deployment gate": "بوابة النشر النهائية",
  "Final integration command failed.": "فشل أمر التكامل النهائي.",
  "Final Owner Integration": "تكامل المالك النهائي",
  "Final platform integration synchronization failed.":
    "فشلت مزامنة التكامل النهائي للمنصة.",
  "Final platform integration synchronized.":
    "تمت مزامنة التكامل النهائي للمنصة.",
  "Final readiness closed at": "أُغلقت الجاهزية النهائية عند",
  "Finalization backend contract is not available.":
    "عقد خادم الإنهاء غير متاح.",
  "Find an Owner Module": "العثور على وحدة للمالك",
  "Footer columns JSON is not valid yet.":
    "JSON الخاص بأعمدة التذييل غير صالح بعد.",
  "Full visibility into owner decisions, approvals, internal staff actions, policy changes, incidents and governance events.":
    "رؤية كاملة لقرارات المالك والموافقات وإجراءات الموظفين الداخليين وتغييرات السياسات والحوادث وأحداث الحوكمة.",
  "Generated by the backend": "مولّد بواسطة الخادم",
  "Global Command Center": "مركز القيادة العامة",
  "Global control of plans, users, services, policies, risk and organization boundaries.":
    "تحكم عام في الخطط والمستخدمين والخدمات والسياسات والمخاطر وحدود المؤسسات.",
  "Global Governance Policies": "سياسات الحوكمة العامة",
  "Global Project Oversight": "الإشراف العام على المشروعات",
  "Go to AI Agents": "الانتقال إلى وكلاء الذكاء الاصطناعي",
  "Go to AI Providers": "الانتقال إلى مزودي الذكاء الاصطناعي",
  "Go to Knowledge": "الانتقال إلى المعرفة",
  "Go to Meetings": "الانتقال إلى الاجتماعات",
  "Go to Monitoring": "الانتقال إلى المراقبة",
  "Go to Overview": "الانتقال إلى النظرة العامة",
  "Go to Projects": "الانتقال إلى المشروعات",
  "Go to Reports": "الانتقال إلى التقارير",
  "Go to Security": "الانتقال إلى الأمان",
  "Go to Servers": "الانتقال إلى الخوادم",
  "Go to Settings": "الانتقال إلى الإعدادات",
  "Go to Tasks": "الانتقال إلى المهام",
  "Go to Workflows": "الانتقال إلى مسارات العمل",
  "Governance Guardrails": "ضوابط الحوكمة",
  "High risk": "مخاطر مرتفعة",
  "Incidents & Emergency Response": "الحوادث والاستجابة للطوارئ",
  "Initial password": "كلمة المرور الأولية",
  "Integration command failed.": "فشل أمر التكامل.",
  "Integration completion": "اكتمال التكامل",
  "Invalid JSON": "JSON غير صالح",
  "Keep current plan": "الإبقاء على الخطة الحالية",
  "Keep current priority": "الإبقاء على الأولوية الحالية",
  "Language saved.": "تم حفظ اللغة.",
  "Last check": "آخر فحص",
  "Latest backend-reported dependency nodes and health. Refresh to request a new snapshot.":
    "أحدث عقد الاعتماد وحالتها كما أبلغ الخادم. حدّث لطلب لقطة جديدة.",
  "Leave blank to keep the current name":
    "اتركه فارغًا للإبقاء على الاسم الحالي",
  "License action failed and was not persisted.":
    "فشل إجراء الترخيص ولم يُحفظ.",
  "License registry synchronized.": "تمت مزامنة سجل التراخيص.",
  "Licensed seats": "المقاعد المرخّصة",
  "Licensing backend contract is not available.": "عقد خادم التراخيص غير متاح.",
  "Limited Services": "الخدمات المحدودة",
  "linked item": "عنصر مرتبط",
  "Live core-data probes plus configuration status for AI providers and cloud credentials.":
    "فحوص مباشرة للبيانات الأساسية وحالة إعداد مزودي الذكاء الاصطناعي وبيانات اعتماد السحابة.",
  "Live Dependencies & Release Approval": "الاعتمادات المباشرة واعتماد الإصدار",
  "Live dependency and release-gate validation completed.":
    "اكتمل التحقق من الاعتمادات وبوابات الإصدار.",
  "Live dependency checks, unresolved critical-incident clearance, explicit performance telemetry, verified restore evidence, and Owner approval.":
    "فحوص الاعتمادات المباشرة وتصفية الحوادث الحرجة غير المحلولة وقياس أداء صريح ودليل استعادة موثق وموافقة المالك.",
  "Live dependency health and evidence-backed release gates, plus the complete Owner route inventory.":
    "صحة الاعتمادات المباشرة وبوابات إصدار مدعومة بالأدلة، إضافة إلى جرد كامل لمسارات المالك.",
  "Live dependency health, alert state, and durable backup and recovery requests.":
    "صحة الاعتمادات المباشرة وحالة التنبيهات وطلبات النسخ الاحتياطي والاستعادة الدائمة.",
  "Live dependency readiness": "جاهزية الاعتمادات المباشرة",
  "Live health evidence for the backend dependencies exposed by the production runtime contract.":
    "دليل صحة مباشر لاعتمادات الخادم التي يعرضها عقد تشغيل الإنتاج.",
  "Live owner visibility for IAM, external secret references, critical alerts, and compliance evidence.":
    "رؤية مباشرة للمالك لإدارة الهوية والوصول ومراجع الأسرار الخارجية والتنبيهات الحرجة وأدلة الامتثال.",
  "Live owner-level visibility across organizations, projects, users and active incidents.":
    "رؤية مباشرة على مستوى المالك للمؤسسات والمشروعات والمستخدمين والحوادث النشطة.",
  "Live projects": "المشروعات المباشرة",
  "Live records": "السجلات المباشرة",
  "Live runtime evidence and Owner authorization for release. CodeQL, build, and test results remain authoritative in the external workflow and are never inferred from these runtime checks.":
    "دليل تشغيل مباشر وتفويض المالك للإصدار. تظل نتائج CodeQL والبناء والاختبارات مرجعية في المسار الخارجي ولا تُستنتج من فحوص التشغيل هذه.",
  "Live Super Owner decisions for pending meeting requests.":
    "قرارات مباشرة من المالك الأعلى لطلبات الاجتماعات المعلقة.",
  "Live validation signals": "إشارات التحقق المباشرة",
  "Loading controlled entities...": "جارٍ تحميل الكيانات المتحكم بها...",
  "Loading executive metrics...": "جارٍ تحميل المقاييس التنفيذية...",
  "Loading external secret references...":
    "جارٍ تحميل مراجع الأسرار الخارجية...",
  "Loading governed projects...": "جارٍ تحميل المشروعات المحكومة...",
  "Loading live approval requests…": "جارٍ تحميل طلبات الموافقة المباشرة…",
  "Loading live owner control data…": "جارٍ تحميل بيانات تحكم المالك المباشرة…",
  "loading live records": "جارٍ تحميل السجلات المباشرة",
  "Loading live references...": "جارٍ تحميل المراجع المباشرة...",
  "Loading organizations...": "جارٍ تحميل المؤسسات...",
  "Loading owner audit events...": "جارٍ تحميل أحداث تدقيق المالك...",
  "Loading portal control...": "جارٍ تحميل تحكم البوابة...",
  "Loading recovery records...": "جارٍ تحميل سجلات الاستعادة...",
  "Loading release gates...": "جارٍ تحميل بوابات الإصدار...",
  "Loading staff records...": "جارٍ تحميل سجلات الموظفين...",
  "Loading topology snapshot...": "جارٍ تحميل لقطة بنية النظام...",
  "Logo & icons": "الشعار والأيقونات",
  "Manage rotation": "إدارة التدوير",
  "Managed users": "المستخدمون المُدارون",
  "Mandatory Release Gates": "بوابات الإصدار الإلزامية",
  "Mark all read": "تحديد الكل كمقروء",
  "Meeting Approvals Center": "مركز موافقات الاجتماعات",
  "Monthly Budget": "الميزانية الشهرية",
  "Navigate to a page or Owner module…": "انتقل إلى صفحة أو وحدة للمالك…",
  "New decision": "قرار جديد",
  "New policy": "سياسة جديدة",
  "No approval requests are currently pending.":
    "لا توجد طلبات موافقة معلقة حاليًا.",
  "No backup or recovery requests exist yet.":
    "لا توجد طلبات نسخ احتياطي أو استعادة بعد.",
  "No billing accounts match this search.":
    "لا توجد حسابات فوترة تطابق هذا البحث.",
  "No communication channels are configured.": "لا توجد قنوات اتصال مضبوطة.",
  "No compliance controls match the selected filters.":
    "لا توجد ضوابط امتثال تطابق المرشحات المحددة.",
  "No controlled entities match the current filters.":
    "لا توجد كيانات متحكم بها تطابق المرشحات الحالية.",
  "No executive metrics are available.": "لا توجد مقاييس تنفيذية متاحة.",
  "No external secret references match the current filters.":
    "لا توجد مراجع أسرار خارجية تطابق المرشحات الحالية.",
  "No governance decisions are configured.": "لا توجد قرارات حوكمة مضبوطة.",
  "No health signals were returned by the Owner API.":
    "لم تُرجع واجهة المالك أي إشارات صحة.",
  "No Limit": "بلا حد",
  "No limit configured": "لم يُضبط حد",
  "No live executive signal currently requires owner attention.":
    "لا توجد إشارة تنفيذية مباشرة تتطلب انتباه المالك حاليًا.",
  "No matching Owner page.": "لا توجد صفحة مالك مطابقة.",
  "No matching page found.": "لم يتم العثور على صفحة مطابقة.",
  "No release gates are configured.": "لا توجد بوابات إصدار مضبوطة.",
  "No roles match the current search.": "لا توجد أدوار تطابق البحث الحالي.",
  "No service budgets are configured.": "لا توجد ميزانيات خدمات مضبوطة.",
  "No services match this category.": "لا توجد خدمات تطابق هذه الفئة.",
  "No successful snapshot yet.": "لا توجد لقطة ناجحة بعد.",
  "Non-active Accounts": "الحسابات غير النشطة",
  "not connected": "غير متصل",
  "Notification & Delivery Control": "التحكم في الإشعارات والتسليم",
  "Notification Center": "مركز الإشعارات",
  "Notification Routing Rules": "قواعد توجيه الإشعارات",
  "Notification rule updated.": "تم تحديث قاعدة الإشعار.",
  "Notification rules backend contract is not available.":
    "عقد خادم قواعد الإشعارات غير متاح.",
  "Notification rules synchronized.": "تمت مزامنة قواعد الإشعارات.",
  "Notification update failed and was not persisted.":
    "فشل تحديث الإشعار ولم يُحفظ.",
  "One discoverable control plane for every Owner page already present in the platform.":
    "طبقة تحكم واحدة قابلة للاكتشاف لكل صفحة مالك موجودة في المنصة.",
  "Open as external link": "فتح كرابط خارجي",
  "Open incident command": "فتح قيادة الحوادث",
  "Open portal": "فتح البوابة",
  "Open registry": "فتح السجل",
  "Open release pipeline": "فتح مسار الإصدار",
  "Operational Dependencies & Recovery": "الاعتمادات التشغيلية والاستعادة",
  "Operations command failed.": "فشل أمر العمليات.",
  "Operations readiness": "جاهزية العمليات",
  "Operations synchronization failed.": "فشلت مزامنة العمليات.",
  "Operations validation completed.": "اكتمل التحقق من العمليات.",
  "Organization Licensing Status": "حالة تراخيص المؤسسات",
  "Organizations & Tenants": "المؤسسات والمستأجرون",
  "Overall completion": "الاكتمال الإجمالي",
  "Override any client translation using keys such as":
    "تجاوز أي ترجمة في العميل باستخدام مفاتيح مثل",
  "Owner action": "إجراء المالك",
  "Owner attestation completed.": "اكتمل إقرار المالك.",
  "Owner Audit & Accountability": "تدقيق المالك والمساءلة",
  "Owner control for organization plans, current seats, access suspension and restoration.":
    "تحكم المالك في خطط المؤسسات والمقاعد الحالية وإيقاف الوصول واستعادته.",
  "Owner CRUD Gateway": "بوابة عمليات المالك",
  "Owner Decision Queue": "قائمة قرارات المالك",
  "Owner Decision Registry": "سجل قرارات المالك",
  "Owner default organization": "المؤسسة الافتراضية للمالك",
  "Owner Executive BI": "ذكاء أعمال المالك التنفيذي",
  "Owner Global Timeline": "الخط الزمني العام للمالك",
  "Owner Navigation Search": "بحث تنقل المالك",
  "Owner notifications": "إشعارات المالك",
  "Owner operation failed.": "فشلت عملية المالك.",
  "Owner Platform Integration": "تكامل منصة المالك",
  "Owner priorities": "أولويات المالك",
  "Owner Realtime Control": "تحكم المالك المباشر",
  "Owner review of live backend dependency health and non-owner release gates before recording release approval.":
    "مراجعة المالك لصحة اعتمادات الخادم المباشرة وبوابات الإصدار غير التابعة للمالك قبل تسجيل اعتماد الإصدار.",
  "Owner runtime backend contract is not available.":
    "عقد خادم تشغيل المالك غير متاح.",
  "Owner timeline backend contract is not available.":
    "عقد خادم الخط الزمني للمالك غير متاح.",
  "Owner Tools": "أدوات المالك",
  "Owner visibility across every project, organization, approval, risk and execution state.":
    "رؤية المالك لكل مشروع ومؤسسة وموافقة ومخاطرة وحالة تنفيذ.",
  "Owner visibility across ISO 27001, SOC 2, GDPR and NIST controls, evidence, risk and remediation.":
    "رؤية المالك لضوابط ISO 27001 وSOC 2 وGDPR وNIST والأدلة والمخاطر والمعالجة.",
  "Owner visibility over platform failures, security events, response teams and resolution state.":
    "رؤية المالك لأعطال المنصة والأحداث الأمنية وفرق الاستجابة وحالة الحل.",
  "Owner-level continuity controls for protected backups, restore validation, failover readiness and recovery evidence.":
    "ضوابط استمرارية على مستوى المالك للنسخ المحمية والتحقق من الاستعادة وجاهزية التحول ودليل التعافي.",
  "Owner-only channels": "قنوات خاصة بالمالك",
  "Owner-only governance for references to credentials held by an external vault. Secret values are never entered or stored here.":
    "حوكمة خاصة بالمالك لمراجع بيانات الاعتماد المحفوظة في خزنة خارجية. لا تُدخل القيم السرية ولا تُخزن هنا.",
  "Owner-only operational inventory and active-incident intelligence from the executive backend snapshot.":
    "جرد تشغيلي وذكاء للحوادث النشطة خاصان بالمالك من لقطة الخادم التنفيذية.",
  "Owner-only visibility into internal roles, departments, organizations and current operating status.":
    "رؤية خاصة بالمالك للأدوار الداخلية والأقسام والمؤسسات وحالة التشغيل الحالية.",
  "Pages & SEO": "الصفحات وتحسين الظهور",
  "Password change failed": "فشل تغيير كلمة المرور",
  "Pause active and running projects? Planning, review, completed, archived and deleted projects are preserved.":
    "هل تريد إيقاف المشروعات النشطة والجارية مؤقتًا؟ ستُحفظ المشروعات المخططة وقيد المراجعة والمكتملة والمؤرشفة والمحذوفة.",
  "Pause active projects": "إيقاف المشروعات النشطة مؤقتًا",
  "Pending meeting decisions": "قرارات الاجتماعات المعلقة",
  "Pending meeting requests": "طلبات الاجتماعات المعلقة",
  "Pending Review": "قيد المراجعة",
  "Persist owner allow/block policies for optional platform services. Runtime credentials remain deployment-managed.":
    "احفظ سياسات السماح والحظر الخاصة بالمالك لخدمات المنصة الاختيارية. تظل بيانات اعتماد التشغيل مُدارة عبر النشر.",
  "Persist routing declarations for project, incident and clarification events. A channel delivers only when its provider and event consumer are connected.":
    "احفظ إعلانات التوجيه لأحداث المشروع والحوادث وطلبات التوضيح. لا تسلّم القناة إلا عند اتصال مزودها ومستقبل الحدث.",
  "plan · organization access status": "الخطة · حالة وصول المؤسسة",
  "Plan ID:": "معرّف الخطة:",
  "Plans & Pricing": "الخطط والأسعار",
  "Platform Connectivity": "اتصال المنصة",
  "Platform integration snapshot synchronized.":
    "تمت مزامنة لقطة تكامل المنصة.",
  "Platform integration synchronization failed.": "فشلت مزامنة تكامل المنصة.",
  "Policy name": "اسم السياسة",
  "Portal control failed to load.": "فشل تحميل تحكم البوابة.",
  "Pricing page enabled": "صفحة الأسعار مفعلة",
  "Production readiness": "جاهزية الإنتاج",
  "Production Readiness & Closure": "جاهزية الإنتاج والإغلاق",
  "Production runtime command failed.": "فشل أمر تشغيل الإنتاج.",
  "Production runtime synchronization failed.": "فشلت مزامنة تشغيل الإنتاج.",
  "Production runtime synchronized.": "تمت مزامنة تشغيل الإنتاج.",
  "Protected assets": "الملفات المحمية",
  "Protected Entity Operations": "عمليات الكيانات المحمية",
  "Protected Meeting Approval Workflow": "مسار موافقة الاجتماعات المحمي",
  "Provide at least one field to update.":
    "قدّم حقلًا واحدًا على الأقل للتحديث.",
  "Provide only metadata and the external reference identifier. Do not paste a password, token, API key or secret value.":
    "قدّم البيانات الوصفية ومعرّف المرجع الخارجي فقط. لا تلصق كلمة مرور أو رمزًا أو مفتاح API أو قيمة سرية.",
  "Public origin:": "المصدر العام:",
  "Publication history": "سجل النشر",
  "Publish failed.": "فشل النشر.",
  "Publish this portal configuration to all ai.vip-e.net visitors?":
    "هل تريد نشر إعدادات البوابة هذه لكل زوار ai.vip-e.net؟",
  "Publishing portal configuration...": "جارٍ نشر إعدادات البوابة...",
  "Queue a durable on-demand PostgreSQL backup job.":
    "أضف مهمة نسخ احتياطي دائمة لـPostgreSQL عند الطلب.",
  "Queue a real restore drill and persist its release evidence.":
    "أضف تدريب استعادة حقيقيًا واحفظ دليل الإصدار الخاص به.",
  "Queue backup": "إضافة مهمة نسخ احتياطي",
  "Queue restore drill": "إضافة تدريب استعادة",
  "Queue restore validation": "إضافة تحقق من الاستعادة",
  "reachable Owner page": "صفحة مالك قابلة للوصول",
  "Readiness check failed": "فشل فحص الجاهزية",
  "Recent owner audit events": "أحداث تدقيق المالك الأخيرة",
  "Record evidence": "تسجيل الدليل",
  "Record ID": "معرّف السجل",
  "Record ID is required for this operation.":
    "معرّف السجل مطلوب لهذه العملية.",
  "Record Owner-approved budget targets. Usage remains explicitly unavailable until a billing telemetry source is connected.":
    "سجل أهداف الميزانية المعتمدة من المالك. يظل الاستخدام غير متاح بوضوح حتى توصيل مصدر قياس للفوترة.",
  "Record release approval": "تسجيل اعتماد الإصدار",
  "Record release approval from the current live dependency and non-owner gate evidence?":
    "هل تريد تسجيل اعتماد الإصدار استنادًا إلى دليل الاعتمادات المباشرة وبوابات غير المالك الحالية؟",
  "Record rotation": "تسجيل التدوير",
  "Recording compliance evidence reference...":
    "جارٍ تسجيل مرجع دليل الامتثال...",
  "Recording…": "جارٍ التسجيل…",
  "Refresh audit": "تحديث التدقيق",
  "Refresh controls": "تحديث الضوابط",
  "Refresh health": "تحديث الصحة",
  "Refresh organizations": "تحديث المؤسسات",
  "Refresh topology": "تحديث البنية",
  "Register an external vault reference": "تسجيل مرجع خزنة خارجية",
  "Release approval recorded": "تم تسجيل اعتماد الإصدار",
  "Release Approved": "الإصدار معتمد",
  "Release Authority & Quality Gates": "سلطة الإصدار وبوابات الجودة",
  "No validated rollback drill evidence recorded yet.":
    "لم يُسجل دليل تدريب رجوع موثق حتى الآن.",
  "Rollback evidence": "دليل الرجوع",
  "No validated deployment evidence recorded yet.":
    "لم يُسجل دليل نشر موثق حتى الآن.",
  "Deployment evidence": "دليل النشر",
  "Review quality-gate evidence, Owner approval, and retained live deployment and rollback evidence for the current production build.":
    "راجع أدلة بوابات الجودة وموافقة المالك وأدلة النشر والرجوع المباشرة المحفوظة للبناء الإنتاجي الحالي.",
  "Release candidates synchronized.": "تمت مزامنة مرشحي الإصدار.",
  "Release decision failed and was not persisted.":
    "فشل قرار الإصدار ولم يُحفظ.",
  "Release governance backend contract is not available.":
    "عقد خادم حوكمة الإصدار غير متاح.",
  "Release Readiness & Final Approval": "جاهزية الإصدار والاعتماد النهائي",
  "Release state": "حالة الإصدار",
  "Request changes": "طلب تعديلات",
  "Reset failed.": "فشلت إعادة الضبط.",
  "Reset the draft to the safe AIONEX defaults? Published visitors will not be affected.":
    "هل تريد إعادة المسودة إلى إعدادات AIONEX الآمنة؟ لن يتأثر الزوار بالإصدار المنشور.",
  "Restore drill queued. Track its durable worker status in the Recovery Center.":
    "أُضيف تدريب الاستعادة. تابع حالة العامل الدائمة في مركز الاستعادة.",
  "Restore the latest protected archive into an isolated scratch database.":
    "استعد أحدث أرشيف محمي داخل قاعدة بيانات اختبار معزولة.",
  "Restricted tenants": "المستأجرون المقيّدون",
  "Resume paused projects": "استئناف المشروعات المتوقفة مؤقتًا",
  "Resume paused projects? All other project states are preserved.":
    "هل تريد استئناف المشروعات المتوقفة مؤقتًا؟ ستُحفظ كل حالات المشروعات الأخرى.",
  "Review pending approvals": "مراجعة الموافقات المعلقة",
  "Review pending meeting requests that require a Super Owner decision.":
    "راجع طلبات الاجتماعات المعلقة التي تتطلب قرار المالك الأعلى.",
  "Review quality-gate evidence and persist the Owner decision for the current build. This registry does not execute a deployment.":
    "راجع دليل بوابات الجودة واحفظ قرار المالك للبناء الحالي. هذا السجل لا ينفذ النشر.",
  "Revoke reference": "إلغاء المرجع",
  "role records": "سجلات أدوار",
  "Rollback and publish": "الرجوع والنشر",
  "Rollback failed": "فشل الرجوع",
  "Run checks": "تشغيل الفحوص",
  "Run DR drill": "تشغيل تدريب التعافي",
  "Run live checks": "تشغيل الفحوص المباشرة",
  "Running live health checks...": "جارٍ تشغيل فحوص الصحة المباشرة...",
  "Running…": "جارٍ التشغيل…",
  "Save decision": "حفظ القرار",
  "Save failed": "فشل الحفظ",
  "Save limit": "حفظ الحد",
  "Save reference": "حفظ المرجع",
  "Search actor, action or target...": "ابحث بالمستخدم أو الإجراء أو الهدف...",
  "Search controls, owners or evidence...":
    "ابحث في الضوابط أو المالكين أو الأدلة...",
  "Search every controlled entity...": "ابحث في كل كيان متحكم به...",
  "Search every project...": "ابحث في كل مشروع...",
  "Search integrations...": "ابحث في التكاملات...",
  "Search names, descriptions, or routes…":
    "ابحث بالأسماء أو الأوصاف أو المسارات…",
  "Search organizations, plans or status...":
    "ابحث في المؤسسات أو الخطط أو الحالة...",
  "Search organizations...": "ابحث في المؤسسات...",
  "Search Owner pages": "بحث صفحات المالك",
  "Search policies...": "ابحث في السياسات...",
  "Search references and providers...": "ابحث في المراجع والمزودين...",
  "Search registered Owner pages and live platform records from the protected control plane.":
    "ابحث في صفحات المالك المسجلة وسجلات المنصة المباشرة من طبقة التحكم المحمية.",
  "Search staff, department or organization...":
    "ابحث بالموظف أو القسم أو المؤسسة...",
  "seats active": "مقاعد نشطة",
  "Security command failed.": "فشل أمر الأمان.",
  "Security integrations synchronized.": "تمت مزامنة تكاملات الأمان.",
  "Security readiness": "جاهزية الأمان",
  "Security synchronization failed.": "فشلت مزامنة الأمان.",
  "Security, Identity & Governance": "الأمان والهوية والحوكمة",
  "Select a live organization": "اختر مؤسسة مباشرة",
  "Select a live organization and role, enter a valid email, and use a 12+ character password.":
    "اختر مؤسسة ودورًا مباشرين وأدخل بريدًا صالحًا واستخدم كلمة مرور من 12 حرفًا على الأقل.",
  "Select a live role": "اختر دورًا مباشرًا",
  "Send test": "إرسال اختبار",
  "services enabled": "خدمات مفعلة",
  "Session revoke failed": "فشل تسجيل الخروج من الجلسات",
  "Settings failed": "فشل تحميل الإعدادات",
  "Show tax note": "إظهار ملاحظة الضرائب",
  "Single owner-visible record of project, user, approval, service, incident and security activity.":
    "سجل واحد ظاهر للمالك لنشاط المشروعات والمستخدمين والموافقات والخدمات والحوادث والأمان.",
  "Social links JSON is not valid yet.":
    "JSON الخاص بروابط التواصل غير صالح بعد.",
  "Source Control": "التحكم بالمصدر",
  "Staff Identity & Status": "هوية الموظفين وحالتهم",
  "Start voice input": "بدء الإدخال الصوتي",
  "Stop voice input": "إيقاف الإدخال الصوتي",
  "Submitting owner attestation...": "جارٍ إرسال إقرار المالك...",
  "Subscription periods": "مدد الاشتراك",
  "Subscriptions, Plans & Billing": "الاشتراكات والخطط والفوترة",
  "Suspend or restore roles without affecting the protected owner account. Roles with the same name belong to different organizations and are grouped below.":
    "أوقف الأدوار أو استعدها دون التأثير على حساب المالك المحمي. الأدوار المتشابهة في الاسم تتبع مؤسسات مختلفة وقد جُمعت أدناه حسب المؤسسة.",
  "Telemetry Linked": "القياس متصل",
  "The draft has unsaved changes. Publish the last saved draft instead?":
    "توجد تغييرات غير محفوظة في المسودة. هل تريد نشر آخر مسودة محفوظة بدلًا منها؟",
  "The policy will be persisted as a draft and can be activated after review.":
    "ستُحفظ السياسة كمسودة ويمكن تفعيلها بعد المراجعة.",
  "The release approval was recorded from the current live dependency and gate evidence.":
    "تم تسجيل اعتماد الإصدار من دليل الاعتمادات والبوابات المباشرة الحالية.",
  "Theme & Fonts": "المظهر والخطوط",
  "This is the advanced control surface for every safe configuration field. Executable scripts and unsafe URLs are rejected by the backend.":
    "هذه واجهة التحكم المتقدمة لكل حقول الإعداد الآمنة. يرفض الخادم السكربتات التنفيذية والروابط غير الآمنة.",
  "This registry persists owner decisions. Each operational module remains responsible for enforcing its own protected actions.":
    "يحفظ هذا السجل قرارات المالك. وتظل كل وحدة تشغيل مسؤولة عن إنفاذ إجراءاتها المحمية.",
  "Total events": "إجمالي الأحداث",
  "Total seats": "إجمالي المقاعد",
  "Track deployment configuration and Owner enablement intent for AI, source, cloud, data, security and communication providers. Live probes are shown only where the backend supports them.":
    "تابع إعدادات النشر وقرار المالك بالتفعيل لمزودي الذكاء الاصطناعي والمصدر والسحابة والبيانات والأمان والاتصالات. لا تُعرض الفحوص المباشرة إلا حيث يدعمها الخادم.",
  "Tracked Events": "الأحداث المتتبعة",
  "Translation overrides": "تجاوزات الترجمة",
  "Trend unavailable": "الاتجاه غير متاح",
  "Unified Activity Timeline": "الخط الزمني الموحد للنشاط",
  "Updating notification rule...": "جارٍ تحديث قاعدة الإشعار...",
  "Upload failed": "فشل الرفع",
  "Upload image, icon, logo, or WOFF2 font":
    "رفع صورة أو أيقونة أو شعار أو خط WOFF2",
  "Usage telemetry:": "قياس الاستخدام:",
  "Use icon": "استخدام كأيقونة",
  "Use logo": "استخدام كشعار",
  "users ·": "مستخدمون ·",
  "Validating and saving the draft...": "جارٍ التحقق من المسودة وحفظها...",
  "Validating…": "جارٍ التحقق…",
  "Validation suites": "حزم التحقق",
  "Vault, AWS Secrets Manager...": "Vault أو AWS Secrets Manager...",
  "Verified readiness result": "نتيجة الجاهزية الموثقة",
  "Verify configuration": "التحقق من الإعداد",
  "Verify configured delivery channels and persist Owner enablement choices. Test delivery uses the connected backend provider.":
    "تحقق من قنوات التسليم المضبوطة واحفظ اختيارات المالك للتفعيل. يستخدم التسليم التجريبي مزود الخادم المتصل.",
  "Verifying…": "جارٍ التحقق…",
  "Visitors may dismiss it": "يمكن للزوار إغلاقه",
  "Billing load failed.": "فشل تحميل الفوترة.",
  "Wallet credit must be a positive integer in minor units.":
    "يجب أن يكون رصيد المحفظة عددًا صحيحًا موجبًا بالوحدات الصغرى.",
  "Usage quantity must be a positive integer.":
    "يجب أن تكون كمية الاستخدام عددًا صحيحًا موجبًا.",
  "Settlement note:": "ملاحظة التسوية:",
  "Failure note:": "ملاحظة الفشل:",
  "Offline payment verified": "تم التحقق من الدفع غير المتصل",
  "Offline payment rejected": "تم رفض الدفع غير المتصل",
  "Refund amount is outside the refundable balance.":
    "مبلغ الاسترداد خارج الرصيد القابل للاسترداد.",
  "License seats must be a positive integer.":
    "يجب أن يكون عدد مقاعد الترخيص عددًا صحيحًا موجبًا.",
  "Loading billing control plane...": "جارٍ تحميل طبقة التحكم في الفوترة...",
  "Durable Billing Authority": "سلطة الفوترة الدائمة",
  "Billing, Licensing, Payments & Entitlements":
    "الفوترة والتراخيص والمدفوعات والاستحقاقات",
  "One control plane for public pricing, enforced limits, seats, wallets, usage, subscriptions, invoices, refunds, licenses, verified webhooks, and provider reconciliation.":
    "طبقة تحكم واحدة للأسعار العامة والحدود المطبقة والمقاعد والمحافظ والاستخدام والاشتراكات والفواتير والاستردادات والتراخيص وإشعارات الويب الموثقة ومصالحة المزودين.",
  "Search organizations, plans, or status...":
    "ابحث بالمؤسسة أو الخطة أو الحالة...",
  "active of": "نشط من",
  "licensed seats · period ends": "مقعدًا مرخصًا · تنتهي الفترة",
  "· Entitlements:": "· الاستحقاقات:",
  "No transactions recorded.": "لا توجد معاملات مسجلة.",
  "· Tax": "· الضريبة",
  "· Paid": "· المدفوع",
  "· Refunded": "· المسترد",
  "No invoices recorded.": "لا توجد فواتير مسجلة.",
  "Fixed amount": "مبلغ ثابت",
  "Percent or minor amount": "النسبة أو المبلغ بالوحدة الصغرى",
  "Max redemptions": "الحد الأقصى لمرات الاستخدام",
  "Create coupon": "إنشاء قسيمة",
  "Tax rates": "معدلات الضرائب",
  "Tax code": "رمز الضريبة",
  "Country code": "رمز الدولة",
  "Save tax": "حفظ الضريبة",
  "Organization wallets": "محافظ المؤسسات",
  "Wallets are created on first credit or usage event.":
    "تُنشأ المحافظ عند أول إضافة رصيد أو حدث استخدام.",
  "seats ·": "مقاعد ·",
  "No durable licenses issued.": "لم تُصدر تراخيص دائمة.",
  "Metered usage": "الاستخدام المقاس",
  "used ·": "مستخدم ·",
  "No metered usage recorded.": "لا يوجد استخدام مقاس مسجل.",
  "Mobile stores": "متاجر الهاتف المحمول",
  "Apple App Store": "متجر Apple App Store",
  "Google Play": "متجر Google Play",
  "Server credentials configured": "بيانات اعتماد الخادم مضبوطة",
  "Configuration incomplete": "الإعداد غير مكتمل",
  "Plan ↔ store product mapping": "ربط الخطة بمنتج المتجر",
  "Period (monthly)": "الفترة (شهريًا)",
  "Store product ID": "معرّف منتج المتجر",
  "Base plan (Google)": "الخطة الأساسية (Google)",
  "Offer ID (optional)": "معرّف العرض (اختياري)",
  "Save mapping": "حفظ الربط",
  "Current mappings": "عمليات الربط الحالية",
  "No mobile store mappings configured.":
    "لا توجد عمليات ربط لمتاجر الهاتف مضبوطة.",
  "Readiness diagnostics": "تشخيص الجاهزية",
  "All active plan periods are mapped and store server configuration is ready.":
    "جميع فترات الخطط النشطة مربوطة وإعداد خادم المتجر جاهز.",
  "Payment providers": "مزودو الدفع",
  "Verified webhook ledger": "سجل إشعارات الويب الموثقة",
  "No verified webhook events received.": "لم تُستقبل أحداث Webhook موثقة.",
  "Reconciliation history": "سجل المصالحة",
  "No reconciliation runs yet.": "لم تُنفذ عمليات مصالحة بعد.",
  "Support Command": "قيادة الدعم",
  "Durable support conversations, assignment, and resolution.":
    "محادثات دعم دائمة وإسناد ومعالجة موثقة.",
  "Owner Support Command": "قيادة دعم المالك",
  "Durable Support Operations": "عمليات الدعم الدائمة",
  "Review tenant requests, preserve every message, assign work, and close the loop with auditable status changes.":
    "راجع طلبات المؤسسات واحفظ كل رسالة وأسند العمل وأغلق الدورة بتغييرات حالة قابلة للتدقيق.",
  "Total requests": "إجمالي الطلبات",
  "Open requests": "الطلبات المفتوحة",
  "Resolved requests": "الطلبات المعالجة",
  "Back to requests": "العودة إلى الطلبات",
  "Start work": "بدء العمل",
  Resolve: "معالجة",
  Close: "إغلاق",
  "Write a durable reply": "اكتب ردًا دائمًا",
  "Send reply": "إرسال الرد",
  "Loading support requests…": "جارٍ تحميل طلبات الدعم…",
  "No support requests are currently recorded.":
    "لا توجد طلبات دعم مسجلة حاليًا.",
  "Unable to load support requests.": "تعذر تحميل طلبات الدعم.",
  "Unable to load support request.": "تعذر تحميل طلب الدعم.",
  "Reply delivered and recorded.": "تم تسليم الرد وتسجيله.",
  "Unable to send the reply.": "تعذر إرسال الرد.",
  "Support request status updated.": "تم تحديث حالة طلب الدعم.",
  "Unable to update the support request.": "تعذر تحديث طلب الدعم.",
};

const FR: Catalog = {
  "Sign in": "Connexion",
  "Create a free account": "Créer un compte gratuit",
  Email: "E-mail",
  Password: "Mot de passe",
  Username: "Nom d’utilisateur",
  "Full name": "Nom complet",
  "Date of birth": "Date de naissance",
  "Mobile number": "Numéro de téléphone",
  "Mobile verification": "Vérification mobile",
  "Send code": "Envoyer le code",
  Verify: "Vérifier",
  Projects: "Projets",
  "New Project": "Nouveau projet",
  "Create project": "Créer un projet",
  "Project name": "Nom du projet",
  Description: "Description",
  "Create Project": "Créer le projet",
  "Search projects...": "Rechercher des projets...",
  Settings: "Paramètres",
  Dashboard: "Tableau de bord",
  Notifications: "Notifications",
};

const ES: Catalog = {
  "Sign in": "Iniciar sesión",
  "Create a free account": "Crear una cuenta gratuita",
  Email: "Correo electrónico",
  Password: "Contraseña",
  Username: "Nombre de usuario",
  "Full name": "Nombre completo",
  "Date of birth": "Fecha de nacimiento",
  "Mobile number": "Número de móvil",
  "Mobile verification": "Verificación móvil",
  "Send code": "Enviar código",
  Verify: "Verificar",
  Projects: "Proyectos",
  "New Project": "Nuevo proyecto",
  "Create project": "Crear proyecto",
  "Project name": "Nombre del proyecto",
  Description: "Descripción",
  "Create Project": "Crear proyecto",
  "Search projects...": "Buscar proyectos...",
  Settings: "Configuración",
  Dashboard: "Panel",
  Notifications: "Notificaciones",
};

const DE: Catalog = {
  "Sign in": "Anmelden",
  "Create a free account": "Kostenloses Konto erstellen",
  Email: "E-Mail",
  Password: "Passwort",
  Username: "Benutzername",
  "Full name": "Vollständiger Name",
  "Mobile number": "Mobilnummer",
  "Mobile verification": "Mobilverifizierung",
  "Send code": "Code senden",
  Verify: "Bestätigen",
  Projects: "Projekte",
  "New Project": "Neues Projekt",
  "Create project": "Projekt erstellen",
  "Project name": "Projektname",
  Settings: "Einstellungen",
  Dashboard: "Übersicht",
};

const TR: Catalog = {
  "Sign in": "Giriş yap",
  "Create a free account": "Ücretsiz hesap oluştur",
  Email: "E-posta",
  Password: "Şifre",
  Username: "Kullanıcı adı",
  "Full name": "Ad soyad",
  "Mobile number": "Cep telefonu",
  "Mobile verification": "Mobil doğrulama",
  "Send code": "Kod gönder",
  Verify: "Doğrula",
  Projects: "Projeler",
  "New Project": "Yeni proje",
  Settings: "Ayarlar",
  Dashboard: "Kontrol paneli",
};

const ZH: Catalog = {
  "Sign in": "登录",
  "Create a free account": "创建免费账户",
  Email: "电子邮箱",
  Password: "密码",
  Username: "用户名",
  "Full name": "全名",
  "Mobile number": "手机号码",
  "Mobile verification": "手机验证",
  "Send code": "发送验证码",
  Verify: "验证",
  Projects: "项目",
  "New Project": "新建项目",
  Settings: "设置",
  Dashboard: "仪表板",
};

const HI: Catalog = {
  "Sign in": "साइन इन करें",
  "Create a free account": "मुफ़्त खाता बनाएँ",
  Email: "ईमेल",
  Password: "पासवर्ड",
  Username: "उपयोगकर्ता नाम",
  "Full name": "पूरा नाम",
  "Mobile number": "मोबाइल नंबर",
  "Mobile verification": "मोबाइल सत्यापन",
  "Send code": "कोड भेजें",
  Verify: "सत्यापित करें",
  Projects: "परियोजनाएँ",
  "New Project": "नई परियोजना",
  Settings: "सेटिंग्स",
  Dashboard: "डैशबोर्ड",
};

const UR: Catalog = {
  "Sign in": "سائن اِن",
  "Create a free account": "مفت اکاؤنٹ بنائیں",
  Email: "ای میل",
  Password: "پاس ورڈ",
  Username: "صارف نام",
  "Full name": "پورا نام",
  "Mobile number": "موبائل نمبر",
  "Mobile verification": "موبائل تصدیق",
  "Send code": "کوڈ بھیجیں",
  Verify: "تصدیق کریں",
  Projects: "منصوبے",
  "New Project": "نیا منصوبہ",
  Settings: "ترتیبات",
  Dashboard: "ڈیش بورڈ",
};

function catalogFor(locale: SupportedLocale): Catalog | null {
  if (locale.startsWith("ar-")) return AR;
  if (locale === "fr-FR") return FR;
  if (locale === "es-ES") return ES;
  if (locale === "de-DE") return DE;
  if (locale === "tr-TR") return TR;
  if (locale === "zh-CN") return ZH;
  if (locale === "hi-IN") return HI;
  if (locale === "ur-PK") return UR;
  return null;
}

function translateArabicPattern(core: string): string | null {
  let match = core.match(/^Synchronized (\d+) records\.$/);
  if (match) return `تمت مزامنة ${match[1]} سجلًا.`;
  match = core.match(/^Revoke (\d+) session\(s\)$/);
  if (match) return `تسجيل الخروج من ${match[1]} جلسة أخرى`;
  match = core.match(/^Revoked (\d+) refresh session\(s\)\.$/);
  if (match) return `تم تسجيل الخروج من ${match[1]} جلسة أخرى.`;
  match = core.match(/^Loaded (\d+) approval requests?\.$/);
  if (match) return `تم تحميل ${match[1]} طلب موافقة.`;
  match = core.match(/^Published version (.+)\.$/);
  if (match) return `تم نشر الإصدار ${match[1]}.`;
  match = core.match(/^Draft loaded\. Published version (.+)\.$/);
  if (match) return `تم تحميل المسودة. الإصدار المنشور ${match[1]}.`;
  match = core.match(/^(\d+) users?$/);
  if (match) return `${match[1]} مستخدم`;
  match = core.match(/^(\d+) records?$/);
  if (match) return `${match[1]} سجل`;
  return null;
}

export function translateInterfaceText(
  text: string,
  locale: SupportedLocale,
): string {
  const catalog = catalogFor(locale);
  if (!catalog) return text;
  const leading = text.match(/^\s*/)?.[0] ?? "";
  const trailing = text.match(/\s*$/)?.[0] ?? "";
  const core = text.trim();
  if (!core) return text;
  const patterned = locale.startsWith("ar-")
    ? translateArabicPattern(core)
    : null;
  return `${leading}${catalog[core] ?? patterned ?? core}${trailing}`;
}
