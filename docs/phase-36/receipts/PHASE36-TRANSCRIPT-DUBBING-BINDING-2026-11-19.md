# Phase 36G: ربط checksum التفريغ بالـ node عشان الدبلجة تشتغل (2026-11-19)

## المشكلة
- **اتكشفت في:** تجربة O-14 الحية (`docs/project/receipts/O14-MEDIA-LIVE-20261119.md`).
- **اللي حصل:** الكلام اتولّد، والتفريغ اتعمل، والاتنين نجحوا. لكن الدبلجة رفضت التفريغ بالرسالة `source transcript checksum is not bound to its node`.

## السبب
- `audio_transcript_runtime` بيكتب `transcript_checksum` في صف التنفيذ وفي قايمة الـ provenance بس.
- `audio_dubbing_pipeline` بيدوّر عليه في `operation_metadata` أو `source_metadata` بتوع الـ node.
- **النتيجة:** أي دبلجة من تفريغ في الإنتاج كانت هتفشل.

## الإصلاح
- لما التفريغ يخلص، الـ runtime بيكتب `transcript_checksum` في `operation_metadata` بتاع الـ node كمان.
- اختبار `tests/test_phase36g_audio_transcript_runtime.py` بقى بيتأكد من ده.

## بعد النشر
نعيد تجربة التفريغ ثم الدبلجة حيًّا، ونحدّث إيصال O-14.
