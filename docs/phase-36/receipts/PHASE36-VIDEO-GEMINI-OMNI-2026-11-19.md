# Phase 36F: نقل الفيديو لـ Gemini Omni Flash (2026-11-19)

## ليه
- **Sora 2 اتقفل:** OpenAI قفلت Sora 2 والـ Videos API يوم 2026-09-24 ([صفحة الموديل](https://developers.openai.com/api/docs/models/sora-2)).
- **Veo اتقفل هو كمان:** Google وقفت Veo 3.1 Preview في Gemini API يوم 2026-10-22، وبتوجّه المطورين لـ Gemini Omni Flash على الـ Interactions API.
- **النتيجة:** الـ live run يوم O-14 لقى الفيديو `ready: false`، وحساب OpenAI مفيهوش أي موديل `sora`.

## التغيير
- **`src/aios/video_factory.py`:**
  - قدرة `gemini-omni-1.1-flash`: نص، أو صورة، أو لوجو لفيديو. بجودة 720p، و16:9 أو 9:16، ومدة 4 أو 8 ثواني (المدة بتتطلب في النص).
  - الإعدادات بقى فيها `seconds` و`size`.
- **`app/services/video_providers.py`:**
  - `GeminiOmniVideoAdapter`: بيستخدم `POST /v1beta/interactions` بـ `background: true` و`store: true` و`delivery: "uri"`. الـ poll بـ `GET /v1beta/interactions/{id}`، والتنزيل من Files URI على `generativelanguage.googleapis.com` بس.
  - مفيش reconcile، فلو الإرسال غامض، المقطع بيتقفل ومش بيتبعت تاني ونتدفع مرتين.
  - التسعير: **سقف** لأطول مقطع (10 ثواني بـ 720p، يعني 57,920 video token، زائد أرقام احتياطية للـ thinking والـ input) = حوالي 1.05 دولار للمقطع. **التكلفة الفعلية** بتتحسب من سجل الاستهلاك اللي المزوّد بيرجّعه.
  - الأسعار: input ‏1.50 دولار، وtext output ‏9.00 دولار، وvideo output ‏17.50 دولار، لكل مليون token.
- **`video_provider_worker.py`:**
  - بيختار الـ adapter حسب المزوّد.
  - الـ QA بيقبل أي مقطع من 2.5 لـ 10.5 ثانية لـ Omni.
  - التكلفة `official_token_usage`.
- **`video_pipeline.py`:** بيقبل المسار الجديد، وبيقدّر التكلفة بالدالة الموحدة.
- **`live_media.py`:** الفيديو بقى على مزوّد `gemini`، وجاهزيته في `/capabilities` من inventory بتاع Gemini.
- **مسار Sora:** فاضل في الكود ومتغطي بالاختبارات، بس مبقاش مستخدم.

## الأدلة الحية (مفتاح الإنتاج، 2026-11-19، من غير ما الإنتاج يتغير)
- **طلب متزامن بـ 360p:** فيديو MP4 مدته 10.03 ثانية، 640x360، H.264 وفيه صوت AAC. استهلك 19,310 video token، يعني حوالي 0.34 دولار.
- **Background mode بـ 360p، مع طلب "about 4 seconds":** POST رجع `in_progress` في 1.9 ثانية، وبعد 3 مرات poll بقى `completed`. استهلك 7,724 video token، يعني حوالي 4 ثواني، وتكلفته حوالي 0.135 دولار. اتنزل من Files URI بـ 200 من غير أي redirect.

## الاختبارات
- `tests/test_phase36f_video_factory.py`
- `web-dashboard/backend/tests/test_phase36f_video_providers.py`: 4 اختبارات Omni جداد.
- `web-dashboard/backend/tests/test_live_media_api.py`: الفيديو بيتجهز على Gemini، والتكلفة المتوقعة أقل من أو تساوي السقف.
