# حزمة مراجعة تطبيق Meta (App Review) لـ AIONEX-AIOS

هذه الحزمة تجهّز طلب مراجعة تطبيق Meta للبند 3.8 في `COMPLETION-ROADMAP.md`. أسماء الصلاحيات والإعدادات مكتوبة بالإنجليزي كما تظهر في لوحة Meta.

> **الحالة:** الكود مدموج ومختبر باختبارات الوحدة فقط. بقرار المالك (2026-11-06)، أي تجربة حية بحسابات حقيقية، ومنها تسجيل الفيديوهات وإرسال الطلب، تتم قبل إطلاق الويب الكامل. لا يُقال عن أي صلاحية إنها شغالة حيًا قبل التحقق.

## 1. بيانات التطبيق

| البند | القيمة |
|---|---|
| App ID | `1056852290270430` |
| App name | `AIONEX-AIOS` |
| App type | Business |
| بوابة المستخدم | `https://ai.vip-e.net` |
| الـ API | `https://api.vip-e.net/api/v1` |
| OAuth redirect (callback) | `https://api.vip-e.net/api/v1/social/oauth/meta/callback` |
| Webhooks callback URL | `https://api.vip-e.net/api/v1/social/meta/webhooks` |
| Deauthorize callback URL | `https://api.vip-e.net/api/v1/social/meta/deauthorize` |
| Data deletion callback URL | `https://api.vip-e.net/api/v1/social/meta/data-deletion` |
| Data deletion instructions URL | `https://ai.vip-e.net/en/legal/data-deletion/` |
| Privacy policy URL | `https://ai.vip-e.net/en/legal/privacy/` |
| Terms of service URL | `https://ai.vip-e.net/en/legal/terms/` |
| Graph API version | `v26.0` (من `META_GRAPH_API_VERSION`) |

كل استدعاء لـ Graph API يرسل التوكن في رأس `Authorization` فقط، ومعه `appsecret_proof`. التوكنات محفوظة مشفرة (Fernet) ولا تصل للمتصفح.

## 2. الصلاحيات المطلوبة والاستخدام الفعلي لكل واحدة

كل الصلاحيات تحتاج **Advanced Access** لأن التطبيق يخدم صفحات يملكها مستخدمون آخرون غيرنا. الطلب يكون للصلاحيات دي بس، ومحدش منها بيُستخدم في إعلانات أو تحليل خارج التطبيق.

| Permission | ليه محتاجينها | الاستخدام الدقيق داخل التطبيق | الشاشة | Graph API |
|---|---|---|---|---|
| `pages_show_list` | عرض الصفحات اللي المستخدم أدمن عليها علشان يختار منها | بعد تسجيل الدخول بفيسبوك تظهر قائمة الصفحات ليختار المستخدم اللي عايز يربطها | `/{locale}/social/` (نافذة اختيار الحسابات) | `GET /me/accounts` |
| `business_management` | الصفحات وحسابات إنستجرام المملوكة عبر Business Portfolio لا تظهر في القائمة بدونها | نفس نافذة الاختيار: تظهر صفحات وحسابات الـ Business Portfolio | `/{locale}/social/` | `GET /me/accounts` (أصول الـ Business) |
| `pages_read_engagement` | قراءة بيانات الصفحة ومنشوراتها وروابط المنشورات المنشورة | فحص صحة الحساب، ورابط "عرض المنشور" في التقويم، وقراءة منشورات الصفحة للمزامنة الاحتياطية للتعليقات | `/{locale}/social/`، `/{locale}/social/calendar/`، `/{locale}/social/inbox/` | `GET /{page-id}`، `GET /{post-id}?fields=permalink_url`، `GET /{page-id}/feed` |
| `pages_manage_posts` | النشر على الصفحة | محرر المنشورات: نشر نص ورابط وصورة وعدة صور وفيديو، الآن أو بالجدولة | `/{locale}/social/compose/` | `POST /{page-id}/feed`، `/photos`، `/videos` |
| `pages_read_user_content` | قراءة التعليقات اللي كتبها المستخدمون على منشورات الصفحة | تظهر التعليقات في صندوق الوارد الموحد كمحادثات | `/{locale}/social/inbox/` | Webhook `feed`، `GET /{page-id}/feed?fields=comments{...}` |
| `pages_manage_engagement` | الرد على التعليقات وإخفاؤها | زر "إرسال" للرد العلني على تعليق، وزر "إخفاء التعليق" و"إظهار التعليق" | `/{locale}/social/inbox/` | `POST /{comment-id}/comments`، `POST /{comment-id}` مع `is_hidden` |
| `pages_manage_metadata` | اشتراك الصفحة في Webhooks التطبيق | زر "فعّل التحديث الفوري" لكل حساب في صندوق الوارد | `/{locale}/social/inbox/` | `POST /{page-id}/subscribed_apps` بالحقول `feed,messages` |
| `pages_messaging` | قراءة رسائل Messenger والرد عليها | محادثات Messenger في صندوق الوارد، والرد خلال نافذة 24 ساعة فقط (`messaging_type=RESPONSE`). خارج النافذة الرد ممنوع ويظهر تحذير | `/{locale}/social/inbox/` | Webhook `messages`، `GET /{page-id}/conversations?platform=messenger`، `POST /{page-id}/messages` |
| `instagram_basic` | قراءة بيانات حساب Instagram Business المربوط بالصفحة ووسائطه | عرض الحساب في نافذة الاختيار، وقراءة الوسائط للمزامنة الاحتياطية للتعليقات | `/{locale}/social/`، `/{locale}/social/inbox/` | `instagram_business_account{...}`، `GET /{ig-user-id}/media` |
| `instagram_content_publish` | النشر على إنستجرام | محرر المنشورات: صورة، وكاروسيل، وفيديو/Reel عبر الـ container | `/{locale}/social/compose/` | `POST /{ig-user-id}/media`، `POST /{ig-user-id}/media_publish` |
| `instagram_manage_comments` | قراءة تعليقات إنستجرام والرد عليها وإخفاؤها | محادثات التعليقات في صندوق الوارد، والرد، والإخفاء والإظهار | `/{locale}/social/inbox/` | Webhook `comments`، `POST /{ig-comment-id}/replies`، `POST /{ig-comment-id}` مع `hide` |
| `instagram_manage_messages` | قراءة رسائل Instagram Direct والرد عليها | محادثات Instagram Direct في صندوق الوارد، والرد خلال 24 ساعة فقط | `/{locale}/social/inbox/` | Webhook `messages` (Instagram)، `GET /{page-id}/conversations?platform=instagram`، `POST /{page-id}/messages` |

ملاحظات للمراجع (تُكتب في خانة "How will this app use this permission"):

- **لا يوجد إرسال تلقائي:** كل رد يكتبه المستخدم بنفسه ويضغط "إرسال". اقتراح AIONEX AI يملأ خانة الرد فقط، والمستخدم يراجعه قبل الإرسال.
- **لا نطلب Human Agent ولا message tags:** خارج نافذة الـ 24 ساعة الرد ممنوع في الخادم (`messaging-window-closed`) وتظهر رسالة توضح السبب.
- **عزل البيانات:** كل مستخدم يرى محادثات حساباته المربوطة فقط. أي عضو آخر في نفس المؤسسة أو مؤسسة أخرى يحصل على 404.
- **الحذف:** فصل الحساب يحذف التوكن فورًا، وطلب الحذف من فيسبوك يحذف التوكنات ومحادثات صندوق الوارد ويعيد رابط ورمز تأكيد.

## 3. سكريبتات فيديو الشرح للمراجع (Screencasts)

قواعد عامة لكل الفيديوهات:

1. اضبط لغة البوابة على **English** من مبدّل اللغة قبل التسجيل.
2. سجّل الشاشة كاملة بدقة 1080p على الأقل، بدون موسيقى، ومع شرح مكتوب (captions) لكل خطوة.
3. ابدأ كل فيديو من صفحة تسجيل الدخول في `https://ai.vip-e.net/en/login/` واستخدم مستخدم الاختبار الموجود في القسم 4.
4. أظهر نافذة Facebook Login وهي تعرض الصلاحية المطلوبة بوضوح.
5. بعد كل إجراء، افتح فيسبوك أو إنستجرام في تبويب آخر وأظهر النتيجة الفعلية هناك.
6. مدة كل فيديو من 1 إلى 3 دقائق، وفيديو منفصل لكل مجموعة صلاحيات.

### فيديو 1: الربط واختيار الصفحات (`pages_show_list`، `business_management`، `instagram_basic`)

1. سجّل الدخول إلى AIONEX بمستخدم الاختبار.
2. افتح **Social accounts** من القائمة (`/en/social/`).
3. اضغط **Connect** على بطاقة Meta.
4. في نافذة Facebook Login أظهر قائمة الصلاحيات، ثم اختر صفحة الاختبار وحساب إنستجرام المربوط بها، واضغط **Continue**.
5. بعد الرجوع للبوابة تظهر نافذة اختيار الحسابات وفيها صفحة الاختبار وحساب إنستجرام (اسم المستخدم والصورة).
6. اختر الحسابين واضغط **Connect selected**.
7. اضغط **Check health** على الصفحة وأظهر الحالة "Healthy".

### فيديو 2: النشر (`pages_manage_posts`، `instagram_content_publish`، `pages_read_engagement`)

1. افتح **Compose** (`/en/social/compose/`).
2. اكتب نصًا، وارفع صورة JPEG، واختر صفحة الاختبار وحساب إنستجرام.
3. اضغط **Publish now** وانتظر حتى تتحول الحالة إلى **Published**.
4. افتح **Calendar** (`/en/social/calendar/`) واضغط على المنشور، ثم **View live post** لكل حساب.
5. أظهر المنشور على صفحة فيسبوك وعلى حساب إنستجرام.
6. (اختياري) أنشئ منشورًا مجدولًا بعد 5 دقائق وأظهر نشره تلقائيًا.

### فيديو 3: تعليقات فيسبوك (`pages_read_user_content`، `pages_manage_engagement`، `pages_manage_metadata`، `pages_read_engagement`)

1. افتح **Inbox** (`/en/social/inbox/`).
2. في بطاقة صفحة الاختبار اضغط **Turn on live updates** وأظهر التاريخ الذي يظهر بعدها (اشتراك `subscribed_apps`).
3. من حساب فيسبوك آخر (مستخدم اختبار) اكتب تعليقًا على منشور الصفحة.
4. ارجع للصندوق واضغط تحديث: يظهر التعليق كمحادثة غير مقروءة.
5. افتح المحادثة، واكتب ردًا، واضغط **Send**. أظهر الرد تحت التعليق على فيسبوك.
6. اضغط **Hide comment** على تعليق العميل، وأظهر أنه أصبح مخفيًا على فيسبوك، ثم **Unhide comment**.
7. (اختياري) اضغط **Suggest with AIONEX AI** وأظهر أن الاقتراح يملأ الخانة فقط ولا يُرسل.

### فيديو 4: Messenger (`pages_messaging`)

1. من حساب مستخدم الاختبار أرسل رسالة Messenger للصفحة.
2. في **Inbox** اختر فلتر **Facebook** وافتح المحادثة الجديدة.
3. أظهر سطر "You can reply to this message until ..." (نافذة 24 ساعة).
4. اكتب ردًا واضغط **Send**، وأظهر وصول الرد في Messenger عند مستخدم الاختبار.
5. اشرح بالتعليق المكتوب أن الرد بعد 24 ساعة من آخر رسالة للعميل ممنوع، وأن التطبيق يعرض تحذير "The 24-hour window has closed".

### فيديو 5: إنستجرام (`instagram_manage_comments`، `instagram_manage_messages`)

1. من حساب إنستجرام اختبار، علّق على منشور حساب الاختبار وأرسل له رسالة Direct.
2. في **Inbox** اختر فلتر **Instagram**: تظهر محادثة التعليق ومحادثة الرسالة.
3. رد على التعليق، ثم أخفِه وأظهره، وأظهر النتيجة على إنستجرام.
4. رد على الرسالة الخاصة خلال 24 ساعة، وأظهر وصول الرد في إنستجرام.

### فيديو 6: حذف البيانات وإلغاء التفويض

1. في فيسبوك: **Settings & privacy → Settings → Apps and websites**، اختر **AIONEX-AIOS** واضغط **Remove**، ثم اطلب حذف البيانات.
2. أظهر رمز التأكيد والرابط اللذين تعرضهما Meta.
3. افتح الرابط: صفحة `https://ai.vip-e.net/en/legal/data-deletion/?code=...` تعرض الحالة **Completed** وعدد الحسابات والمحادثات المحذوفة.
4. ارجع لـ **Social accounts** وأظهر أن الحسابات أصبحت مفصولة، وأن صندوق الوارد فارغ.

## 4. تعليمات مستخدم الاختبار

- **حساب AIONEX للمراجع:** أنشئ قبل الإرسال حسابًا مخصصًا للمراجعة على باقة تسمح بالنشر والصندوق والذكاء الاصطناعي. اكتب البريد وكلمة المرور في خانة "Notes for reviewer" في لوحة Meta فقط، ولا تكتبهم في المستودع أو أي ملف.
- **التحقق بخطوتين:** عطّل التحقق بالجوال أو اجعله لا يُطلب لهذا الحساب فقط طوال فترة المراجعة، وإلا لن يستطيع المراجع الدخول.
- **حسابات Meta للاختبار:** من **App roles → Test users** أنشئ مستخدم اختبار، ومن **Roles** أضف حسابات فريق المراجعة كـ Testers أثناء وضع Development. جهّز صفحة فيسبوك اختبار يكون مستخدم الاختبار أدمن عليها، وحساب Instagram Professional مربوطًا بها.
- **مستخدم ثانٍ للعميل:** حساب فيسبوك وحساب إنستجرام آخران لكتابة التعليقات وإرسال الرسائل في الفيديوهات 3 و4 و5.
- **خطوات المراجع:** (1) سجّل الدخول على `https://ai.vip-e.net/en/login/` بالبيانات في الملاحظات. (2) افتح **Social accounts** واضغط **Connect** على Meta. (3) اتبع خطوات الفيديوهات بنفس الترتيب.
- **بعد انتهاء المراجعة:** غيّر كلمة مرور حساب المراجع أو عطّله، وأعد تفعيل التحقق بخطوتين.

## 5. قائمة إعدادات التطبيق في لوحة Meta

### App settings → Basic
- [ ] **App domains:** `vip-e.net`، `ai.vip-e.net`، `api.vip-e.net`.
- [ ] **Privacy policy URL:** `https://ai.vip-e.net/en/legal/privacy/` (فيها قسم بيانات Facebook وInstagram وقسم الحذف).
- [ ] **Terms of service URL:** `https://ai.vip-e.net/en/legal/terms/`.
- [ ] **User data deletion:** اختر **Data deletion callback URL** واكتب `https://api.vip-e.net/api/v1/social/meta/data-deletion`. صفحة التعليمات البديلة: `https://ai.vip-e.net/en/legal/data-deletion/`.
- [ ] **App icon** بمقاس 1024×1024، و**Category**، و**Contact email** حقيقي يتابعه فريق الدعم.

### Facebook Login for Business → Settings
- [ ] **Valid OAuth Redirect URIs:** `https://api.vip-e.net/api/v1/social/oauth/meta/callback` فقط.
- [ ] **Client OAuth login:** On. **Web OAuth login:** On. **Enforce HTTPS:** On. **Use Strict Mode for redirect URIs:** On.
- [ ] **Login from Devices:** Off.
- [ ] **Deauthorize callback URL:** `https://api.vip-e.net/api/v1/social/meta/deauthorize`.
- [ ] **Data Deletion Request URL:** `https://api.vip-e.net/api/v1/social/meta/data-deletion`.

### Webhooks
- [ ] **Page** object: Callback URL `https://api.vip-e.net/api/v1/social/meta/webhooks`، و**Verify token** هو نفس قيمة `META_WEBHOOK_VERIFY_TOKEN_FILE` على الخادم (16 حرفًا على الأقل). الحقول: `feed` و`messages`.
- [ ] **Instagram** object: نفس الـ Callback URL والـ Verify token. الحقول: `comments` و`messages`.
- [ ] اضغط **Verify and save** بعد نشر الكود وتجهيز ملف التوكن، وتأكد أن Meta قبلت الـ challenge.
- [ ] اشتراك كل صفحة يتم من زر **Turn on live updates** في صندوق الوارد (`POST /{page-id}/subscribed_apps`).

### Products
- [ ] Facebook Login for Business.
- [ ] Messenger (Messenger API settings، بدون Human Agent).
- [ ] Instagram (Instagram API with Facebook Login).
- [ ] Webhooks.

### إعدادات الخادم (بدون أي قيم سرية في المستودع)
- [ ] `META_APP_ID=1056852290270430`.
- [ ] `META_APP_SECRET_FILE` يشير لملف سري بصلاحيات `0600`.
- [ ] `META_WEBHOOK_VERIFY_TOKEN_FILE` يشير لملف سري بصلاحيات `0600` (أو `META_WEBHOOK_VERIFY_TOKEN`، والملف له الأولوية).
- [ ] `META_OAUTH_SCOPES` يُترك على القيمة الافتراضية (الصلاحيات في القسم 2).
- [ ] `SOCIAL_INBOX_POLL_ENABLED=true` و`SOCIAL_INBOX_POLL_SECONDS=900` للمزامنة الاحتياطية في `social-publish-worker`.
- [ ] nginx فيه الـ location العام `^/api/v1/social/meta/(webhooks|deauthorize|data-deletion)$` (GET وPOST فقط).

### Business Verification
- [ ] من **Meta Business Suite → Business settings → Security Center** اضغط **Start verification**.
- [ ] جهّز الاسم القانوني للشركة المالكة للتطبيق وعنوانها ورقم هاتفها كما في الرخصة التجارية، ونسخة من الرخصة أو السجل التجاري.
- [ ] تحقق من النطاق `vip-e.net` في **Brand safety → Domains** (سجل DNS TXT أو meta-tag).
- [ ] اربط التطبيق بنفس الـ Business Portfolio من **App settings → Basic → Business portfolio**.
- [ ] Advanced Access لصلاحيات الصفحات وإنستجرام لا يُمنح قبل اكتمال Business Verification.

## 6. قبل الإرسال وبعد الموافقة

قبل الإرسال (ضمن نافذة ما قبل الإطلاق):

1. نشر الكود وتطبيق migration `20261106_0068` على الإنتاج.
2. تجهيز ملف `META_WEBHOOK_VERIFY_TOKEN_FILE` وحفظ الـ Webhooks في لوحة Meta.
3. تجربة كل فيديو مرة كاملة بحسابات الاختبار، ثم التسجيل.
4. فتح صفحتي `/en/legal/privacy/` و`/en/legal/data-deletion/` من متصفح بدون تسجيل دخول للتأكد أنهما عامتان.
5. ملء خانة الاستخدام لكل صلاحية من جدول القسم 2، ورفع الفيديو الخاص بها.

بعد الموافقة:

1. تحويل التطبيق إلى **Live mode**.
2. تحقق حي واحد لكل مسار (نشر، تعليق، رد، إخفاء، Messenger، Instagram DM، حذف بيانات) وتسجيل النتيجة في التقرير قبل تغيير حالة البندين 3.6 و3.8 إلى "verified live".
3. متابعة **Data Use Checkup** السنوي من لوحة Meta.
