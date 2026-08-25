# Phase 36J — Complete Course Factory

Date: 2026-08-25

## Scope delivered

- Provider-neutral complete course factory producing curriculum, learning outcomes, lessons, exercises, knowledge checks, teacher answer keys, adaptive paths and citations from one bounded request.
- Six-locale package delivery: Arabic, English, French, German, Spanish and Turkish, including RTL Arabic and localized lesson/quiz/adaptive copy.
- Local generated lesson assets: SVG concept graphic, WAV audio asset and FFmpeg 9 H.264/AAC MP4 preview for each lesson.
- Interactive offline lesson pages with deterministic quiz state, responsive media, citations and local-only resource loading.
- Deterministic checksum-addressed manifest and ZIP, mobile Web App Manifest, online protected site delivery, offline ZIP export, analytics schema and reviewer metadata.
- Durable Alembic 0042 course-package/version/review authority plus per-enrollment lesson progress.
- Academy API for create/list/get/review/download/site/progress/analytics and Academy UI for generation, review and download.
- Dedicated profile-gated non-root Academy Course Worker using the existing FFmpeg 9 media-worker image and a private course-package volume.
- Existing Phase 29F assessment/certification authority is reused rather than duplicated.

## Isolated runtime acceptance

Evidence root: `/opt/AIOS/.deployment-backups/phase36j-acceptance/20260825T062006Z`.

- Alembic round-trip: `0042 -> 0041 -> 0042` PASS; new table count `2 -> 0 -> 2`. Evidence SHA-256 `3c7e9c1732ee05bc6617a67c510bd1deaceeea2bf64a5505ca7a68c0bb0cd79e`.
- Candidate FFmpeg worker image: `sha256:070e6eaae98de9c732a77b6ac551c3d1045ef250e0abecb606b052a4c5076eca`.
- Version 1 built but Browser acceptance found a favicon 404; v1 was rejected rather than relabeled successful.
- Version 2 fixed the browser defect and completed lifecycle acceptance, then a final delivery-security review discovered that the learner ZIP still contained the teacher answer key. v2 was explicitly rejected/superseded and its acceptance certification was revoked.
- Version 3 moves teacher answer/review material under a private subtree excluded from the learner manifest/ZIP/site. The learner ZIP contains zero `_private/` entries and no answer-key file. Privacy evidence SHA-256 `c1b081f5708e55a2ce0ed8be0915e0832bc985ef619dc7e5f06994b13c9f1e8e`.
- Version 3 learner ZIP: `119510` bytes, SHA-256 `0cf73406d051c6b6b2d43250a2f1cfd19ae2d0412d93cad8b3d251022bf38976`; public manifest SHA-256 `ee3471dc08b91ce69ef367faca9bd04471d4e1b551c841c637a2783c4c0c9c15`.
- Browser v3 PASS: 4 lessons, Arabic RTL and localized lesson/quiz content, score 100, audio/video ready, zero console errors and zero external requests. Evidence SHA-256 `2cf09c31dc39738bd492fce3e5d8c70c5b7292e23c08faef076c299b3e98e9dc`.
- Review/lifecycle v3 PASS: sanitized package approved; 4/4 new lesson-progress records completed; assessment score 94 PASS; prior v2 certification revoked; one new v3 acceptance certification active. Evidence SHA-256 `90e74341a6775ed77117bbdc54cf365bbf035ad92b6487e85c083cb936a36886`.
- Teacher answer keys are exposed only through an `academy:assess` endpoint; learner ZIP/site access rejects the private subtree.
- Stale `building` recovery was exercised against the disposable PostgreSQL authority and reclaimed safely.
- Provider requests: 0. Provider/GPU spend: USD 0.00.

## Problems found and corrected before merge

1. The initial Compose edit placed the new volume under the network block and assumed the development Compose had a Media Worker. Production YAML was corrected and the accidental development entry was removed.
2. Initial terse implementation style failed Ruff formatting; changed files were reformatted and linted rather than suppressing the rules.
3. The first isolated fixture flush did not guarantee FK insertion order because these models have no ORM relationships. The acceptance fixture was corrected to explicit dependency-ordered flushes; the product schema was unchanged.
4. Version 1 Browser acceptance found a favicon 404. Version 1 was explicitly rejected, source fixed, and version 2 generated and accepted.
5. The first progress write exposed a real pre-flush ORM default issue: `attempts` could be `None`. The authority now initializes the counter explicitly; the failed transaction rolled back before partial approval.
6. Backend test harness correctly refused a database not explicitly named as disposable/test. A separate `phase36j_test` database was used for tests.
7. A broader Phase29F test first failed closed because the no-lifespan test app was running with production environment semantics. It was rerun under explicit `ENVIRONMENT=test`, preserving the production fail-closed contract.
8. The frontend worktree had no local node_modules. Existing root dependencies were linked temporarily for type/lint/build verification and the link was removed before commit.
9. Phase 36H realtime prerequisite logic was exact-head fragile at 0041. It now treats later linear schema revisions as containing the realtime schema so 0042 does not falsely reopen the old gate.
10. Final delivery review found teacher answer-key material in the learner ZIP. v2 was revoked; v3 excludes all private teacher files from the learner manifest/ZIP/site and exposes the answer key only to `academy:assess`.
11. First protected PR #507 Core run rejected a bare `pass` in the new exception class under zero-dead policy; it was replaced by a descriptive class body and the full Core suite passed `840/840`.
12. Post-merge Production preflight found a fresh named course volume would be root-owned while the worker was configured to start directly as UID 1000. Before worker activation, a follow-up source correction added an idempotent root bootstrap with only CHOWN/FOWNER/SETGID/SETUID, normalized the private volume to 0700:1000:1000, dropped to aionex before Python, and moved the Docker healthcheck to the aionex identity.
13. Fresh-volume runtime proof passed on candidate image `sha256:cbea5689fa0a163194aab1c950ab05f2d45d7cc302fa0b146223088815306a8e`: initial volume `755:0:0` became `700:1000:1000`, command identity became uid/gid 1000, write succeeded, and a second bootstrap preserved the exact inode/mtime metadata. No network was available during either run.
14. One local full-Core validation command stepped two directories up from `web-dashboard` and accidentally collected neighboring worktrees, failing before project tests because those unrelated trees lacked Backend dependencies. It was rerun from the exact hotfix root and passed `840/840`; no source or Production state changed from the harness mistake.

## Truth boundary before Production activation

At this source checkpoint, `course-factory` advances only to `locally_executed`. Production migration 0042, Backend/UI deployment, Academy Course Worker activation and one clean Production synthetic canary are still required before `runtime_verified` and before Batch 36J can close.

No Production database, Production course rows, provider credentials, DNS, firewall, tunnel, external provider, GPU job or paid service was mutated by the isolated acceptance.
## Final production closeout — 2026-08-25

- Protected implementation PR #507 and volume-bootstrap hotfix PR #508 both passed required CI and were merged.
- Production schema is Alembic `20260825_0042`; pre-0042 dump restore manifest remains retained under the deployment-backup evidence tree.
- Backend, Owner Frontend and the dedicated Academy Course Worker were deployed from the merged source tree; the existing Media Worker was not recreated.
- One isolated synthetic Production canary generated a six-locale, four-lesson complete course package with SVG/WAV/MP4/interactive content, citations, adaptive paths and private teacher answer-key/review material. Learner ZIP path traversal/privacy checks passed, and an offline Chromium run passed with 0 external requests and 0 console errors.
- The canary package was approved, all 4 lessons completed, assessment score 92 passed, certification was issued, and analytics reported 4/4 completed lessons.
- All synthetic database rows and course-volume files were deleted after evidence capture; `academy_course_packages` and `academy_lesson_progress` returned to zero rows.
- No external provider request, GPU job, provider spend, DNS/Firewall/Tunnel mutation, or unrelated Media Worker recreation occurred.

Result: `course-factory = runtime_verified`; Batch `36J = complete`; active local batch advances to `36K`.
