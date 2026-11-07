# FR-23 final codebase security review (roadmap 1.6), 2026-11-07

## الملخص بالعربي

- **النطاق:** مراجعة أمنية نهائية لكود AIONEX AIOS نفسه (الكود بس، من غير دخول السيرفر ولا فحص مواقع حية). ركزنا على الأسطح الجديدة: OAuth بتاع Meta، والـ webhooks وحذف البيانات، ورابط الميديا العام الموقّع، ورفع الملفات، والإعلانات وحدود الصرف، وStripe، وSecurity Lab والتحقق بـ DNS، وتوقيع خطة AIONEX AI، وحسابات اختبار الحمل، وبروفة الاسترجاع، وقائمة nginx.
- **بوابات CI جديدة** (`.github/workflows/fr23-security-gates.yml`، كل الـ actions مثبتة بالـ SHA): Semgrep بقواعد مثبتة على commit واحد، وGitleaks على كل تاريخ الريبو، وTrivy للمكتبات وإعدادات Docker/Kubernetes، وpip-audit/npm audit للملفات اللي ماكانش حد بيفحصها. البوابة بتقع على أي ثغرة عالية أو حرجة.
- **أهم اللي لقيناه واتصلح:**
  - **حرجة:** بوابة المستخدم `vip-frontend` كانت على Next.js 15.5.27 وفيه ثغرة تنفيذ كود عن بعد من غير تسجيل دخول (GHSA-2464-fhr4-w9xw). اترفعت لـ 15.5.29. **لازم تتنشر بسرعة.**
  - **متوسطة:** التحقق من ملكية الموقع بملف HTTP في Security Lab كان ممكن يتلف بـ DNS rebinding ويوصل لعنوان داخلي. دلوقتي الطلب بيتثبت على نفس الـ IP اللي اتفحص، وحجم الرد محدود.
  - **متوسطة:** الحزمة الرئيسية كانت بتسمح بـ cryptography أقدم من 47 (46.0.7 فيها 4 ثغرات). بقت `>=50.0.2,<51`.
  - **منخفضة:** قراءة `AndroidManifest.xml` من كود المستخدم بقت بـ defusedxml، وطلبات Meta الموقّعة القديمة (أكتر من 24 ساعة) بتترفض، وتوقيع webhook فيه حروف غير ASCII بقى 400 بدل 500، ومكتبات HTTP مش هتسجل روابط فيها توكنات، وnginx بيرفض أي حرف تحكم في المسار.
  - كل إصلاح ليه اختبار رجوع (regression test).
- **اللي فاضل (خطر متبقي موثق):** **عالية:** عامل TripoSR (بيعالج صور المستخدمين) على Pillow 12.3.0 وفيه ثغرات حرجة، والإصلاح الوحيد Pillow 13 بيتعارض مع rembg، فاتسجل استثناء بينتهي 2026-12-15 وممنوع تشغيل عمال TripoSR قبل إعادة البناء. وكمان مكتبات Go داخل أدوات الفحص المبنية محليًا (محتاجة إعادة بناء)، وصور RunPod شغالة كـ root، وأدوات الفحص النشط بتعمل DNS بنفسها فلازم جدار egress لعامل الفحص. كلها اتسجلت في "سجل ما قبل الإطلاق".
- **مش ادعاء أمان مطلق:** ده فحص للكود. الفحص الحي بعد النشر (FR-23C/E) لسه في نافذة ما قبل الإطلاق.

## Scope

Code only (repository `ipdomx/AIONEX-AIOS`, base `origin/main` 9ee79bb). No server access and no scanning of live hosts.

Manual review covered, in this order:

| Surface | Files |
| --- | --- |
| Social OAuth | `app/services/social_connectors.py`, `social_meta_provider.py`, `social_connections.py`, `app/api/v1/endpoints/social.py` |
| Meta webhooks and data-deletion callbacks | `social_meta_webhooks.py`, `social_data_deletion.py`, `endpoints/social_meta_callbacks.py` |
| Publishing and the signed public media bridge | `social_media_access.py`, `social_media_probe.py`, `endpoints/social_publishing.py`, nginx `/api/v1/social/media/public/...` |
| Uploads (`/api/v1/social/media`, nginx 110 MB) | `social_media_access.store_upload`, `media_storage.py` |
| Ads activation and spend guards | `ads_accounts.py`, `ads_campaigns.py`, `ads_entitlement.py`, `ads_meta_graph.py`, `endpoints/ads.py` |
| Stripe webhooks and billing | `services/billing.py`, `stripe_billing.py`, `endpoints/billing.py` |
| Security Lab entitlement and DNS verification | `security_entitlement.py`, `security_dns_verification.py`, `security_fabric.py`, `endpoints/security_lab.py`, `security_mobile.py` |
| AIONEX AI plan signing | `aionex_ai_plan_signal.py` |
| Synthetic load accounts | `synthetic_load_accounts.py` |
| Restore drill | `restore_drill_fetch.py` |
| Gateway allowlist | `web-dashboard/docker/nginx.conf` |
| Cross-cutting | `core/auth.py` (cookie Origin/Sec-Fetch CSRF guard), `core/logging.py`, `main.py` middleware |

Checks applied to every surface: authz/IDOR and tenancy isolation, SSRF, signature verification and timing-safe comparison, replay and idempotency, open redirects (OAuth callback, Stripe return URLs), CSRF on state-changing routes, upload validation (type sniffing, size, decompression bombs, path traversal), signed-URL scope and expiry, token/secret log leakage, rate limits, error-message leakage, nginx regex anchoring and bypasses, mass assignment in pydantic models.

## Tools and gates

New workflow `.github/workflows/fr23-security-gates.yml` runs on pull requests to `main`, on pushes to `main`, weekly and on demand. All actions are pinned by commit SHA (checkout v7.0.1 `3d3c42e5`, setup-python v7.0.0 `5fda3b95`, setup-node v7.1.0 `949feb24`, trivy-action v0.36.0 `ed142fd0`, upload-artifact v7.0.1 `043fb46d`).

| Job | Tool and pinning | Scope | Fails on |
| --- | --- | --- | --- |
| Semgrep SAST (pinned rules) | Semgrep 1.178.0 from the upstream wheel, SHA-256 `b7c4a4ba…41f2` checked before install; rules from `semgrep/semgrep-rules@16b9e6d45f10649f6a531ec4838ed9924372c3bc` fetched by exact commit | `python/`, `typescript/` (incl. React), `javascript/`, `generic/secrets/`; the OWASP Top 10 rules of these languages live in these directories. Targets: tracked files minus `.semgrepignore` | any ERROR-severity finding |
| Gitleaks full-history secret scan | Gitleaks 8.30.1 built by `web-dashboard/backend/scripts/build_gitleaks.py` from the repository's own lock (source, Go toolchain and binary SHA-256 pinned) | every commit reachable from the checked-out ref (`fetch-depth: 0`, 2,119 commits on the first run), `--redact` | any finding not in `.gitleaksignore` |
| Trivy dependencies and IaC misconfiguration | trivy-action v0.36.0 with Trivy v0.72.0 (same as the Phase 34E container gate) | `fs` scan, scanners `vuln,misconfig`: npm/pip/Go lockfiles, Dockerfiles, Kubernetes manifests | HIGH or CRITICAL not in `.trivyignore.yaml` |
| Dependency audit | pip-audit 2.10.1, npm audit through `.github/scripts/npm-audit-retry.sh` | root `pyproject.toml`, exact-pinned worker manifests, `vip-frontend`, the 3D runtime template lockfile (manifests the Final Validation "Dependency Security" job does not audit) | any pip-audit vulnerability; npm `high`/`critical` |

Existing gates kept unchanged: CodeQL (Python, JS/TS), Final Validation Dependency Security (backend pip-audit, Owner frontend and image-tools npm audit), Phase 34E/34F image SBOM and Trivy image gates, Security Baseline audits.

Compose files are not a Trivy IaC format; they are validated by the existing `docker compose config` steps and by `test_database_settings.py` / `test_private_origin_security_contracts.py`.

## Findings

Severity follows CVSS where an advisory exists, otherwise impact x reachability in this codebase.

| ID | Severity | Location | Issue | Fix | Regression test | Status |
| --- | --- | --- | --- | --- | --- | --- |
| FR23-01 | Critical | `vip-frontend/package.json`, lockfile | Public portal on Next.js 15.5.27: GHSA-2464-fhr4-w9xw (unauthenticated RCE in the image path) and CVE-2026-94482 (DoS). The portal was outside the Dependency Security npm audit. | `next` 15.5.29 with the exact lockfile from the Dependabot branch | Trivy and npm-audit gates on `vip-frontend`; `tests/test_fr06_dependency_security_refresh.py` pins 15.5.29 | Fixed (deploy pending: T-12) |
| FR23-02 | High (residual) | `infra/runpod/triposr/requirements.txt` | The TripoSR worker decodes user images with Pillow 12.3.0 (6 critical heap overflows / code execution, 20+ DoS), Brotli 1.2.0 (critical OOB write), msgpack 1.2.1, rembg 2.0.78 | Not fixable in code today: the only Pillow fix is 13.0.0, and every current rembg release (incl. 2.0.82) requires `pillow<13`. The Phase 34F image build on this PR proved `ResolutionImpossible`, so the bump was reverted. The 31 IDs are listed in `.trivyignore.yaml`, path-scoped, and **expire 2026-12-15**. Mitigation: RunPod endpoints at workersMax=0 (O-07) and RunPod sandbox | The Trivy fs gate re-opens them on expiry; the Phase 34F image gate blocks any TripoSR image change until it is fixed | Residual, blocks enabling TripoSR workers (T-13) |
| FR23-03 | Medium | `web-dashboard/backend/app/services/security_fabric.py` `_http_file_value` | Ownership proof fetch: the SSRF guard resolved the hostname, then httpx resolved it again (DNS-rebinding window to loopback/metadata/private); the whole body was read; transport errors surfaced as 500 | Request pinned to the validated address (Host header and TLS SNI keep the hostname, so certificate checks are unchanged), redirects off, body capped at 4 KiB, `httpx.HTTPError` means "not confirmed" | `tests/test_fr23_security_review.py`: pinned address/Host/SNI, IPv6 and port, rebinding to 127.0.0.1/169.254.169.254/10.0.0.7/::1 never connects, oversized and 302 bodies, connect error | Fixed |
| FR23-04 | Medium | `pyproject.toml` | Root package allowed `cryptography>=41.0.7,<47`; resolution picks 46.0.7 with PYSEC-2026-3552/3553/3554 and GHSA-537c-gmf6-5ccf | `cryptography>=50.0.2,<51` (the backend pin) | pip-audit gate on the root package; Core contracts suite | Fixed |
| FR23-05 | Low | `web-dashboard/backend/app/services/security_mobile.py` | `AndroidManifest.xml` from scanned (untrusted) source trees parsed with stdlib ElementTree | `defusedxml` with `forbid_dtd=True`; refused documents are skipped | `tests/test_security_mobile.py::test_fr23_android_manifest_refuses_dtd_and_entity_expansion` | Fixed |
| FR23-06 | Low | `social_meta_webhooks.parse_signed_request` | Meta `signed_request` had no freshness check: a captured deauthorize/data-deletion request could be replayed later and revoke a grant the person made again | `issued_at` must be an integer within 24 h (5 min future skew) | `test_p3_social_inbox.py::test_fr23_signed_request_replay_outside_the_freshness_window_is_refused`; DB callback tests use a current `issued_at` | Fixed |
| FR23-07 | Low | `services/billing.py` Stripe, Paddle, Paymob/Fawry/STC Pay | `hmac.compare_digest` on `str` raises `TypeError` for a non-ASCII signature header: unauthenticated 500 instead of 400 | `_digest_equal` compares UTF-8 bytes, constant time | `test_fr23_security_review.py`: non-ASCII headers give 400 for three providers; a valid signature after a bad one is still accepted | Fixed |
| FR23-08 | Low | `web-dashboard/docker/nginx.conf` API gateway | PCRE `$` also matches before a trailing newline, so `...%0A` satisfied anchored allowlist regexes. Starlette routes the same way, so no route was reachable that was not allowlisted; defence in depth | Decoded control characters are refused with 400 before any location | `nginx-docker-dns-validation.yml`: `%0A`, `%0D`, `%7F` probes must return 400 | Fixed |
| FR23-09 | Low (latent) | `web-dashboard/backend/app/core/logging.py` | httpx/httpcore log full URLs at INFO; Meta OAuth exchange and token inspection carry the client secret, code or app token in the query. Not emitted today (root logger at WARNING) | `quiet_url_logging()` pins httpx, httpcore, urllib3, botocore, hpack to WARNING in `setup_logging()` | `test_fr23_security_review.py::test_http_client_loggers_never_log_request_urls` | Fixed |
| FR23-10 | Medium (residual) | `web-dashboard/backend/security-build/{gitleaks,httpx,grype,syft,trivy}/go.mod` | Locally built scanner binaries: klauspost/compress CVE-2026-63209, go-jose CVE-2026-116587, x/net CVE-2026-78661/78669, docker/docker CVE-2026-41567/42306 (no upstream fix). Each lock also pins the binary SHA-256, so a module bump needs a rebuild | Path-scoped `.trivyignore.yaml` entries expiring 2026-12-31. The binaries run only in the read-only, `cap_drop: ALL`, non-root Security Lab worker without a Docker socket; the issues are parser DoS or engine-side | Trivy gate re-opens them on expiry | Residual (T-11) |
| FR23-11 | Medium (residual) | `security-scan-worker` (compose network `aionex-network`) | Active scan tools resolve DNS themselves; `assert_target_dns_stable` checks before a scan but cannot stop rebinding during it, and the worker shares a network with backend, Postgres and Redis | None in code | n/a | Residual (T-17) |
| FR23-12 | Low (residual) | `deploy/mobile/android-builder/Dockerfile`, `infra/runpod/triposr/Dockerfile`, `infra/runpod/hunyuan3d/Dockerfile` | Trivy DS-0002: images run as root (offline APK builder; RunPod serverless GPU workers; Hunyuan3D quarantined) | Path-scoped exception expiring 2027-01-31 | Trivy gate | Residual (T-13) |
| FR23-13 | Info | `web-dashboard/backend/Dockerfile` | Trivy DS-0002 on the final stage | Proven false positive: `scripts/docker-entrypoint.sh` always `exec su-exec aionex`; Kubernetes runs it with `runAsNonRoot` | n/a | False positive (documented) |

### Reviewed and found sound (no change)

- **OAuth:** single-use state stored as a digest, browser-bound by an HttpOnly `SameSite=Lax` cookie scoped to the callback path, PKCE where supported, expiry and replay checks under `SELECT ... FOR UPDATE`; the callback only echoes a registered connector key; the portal redirect base is a setting and the locale is allow-listed (no open redirect). Tokens are Fernet-sealed and never serialized.
- **Meta webhooks:** `X-Hub-Signature-256` over the raw body, constant-time; 1 MiB streamed cap; each change is applied once through the `uq_social_webhook_events_key` ledger; verify token compared constant-time and fails closed.
- **Data deletion:** revocation is keyed by the app-scoped Meta user id; the confirmation code is 64 random bits and only a digest of the Meta id is stored.
- **Media bridge:** HMAC token with a domain-separated key, rotation key accepted, expiry capped by settings (300 s to 6 h), filename bound to the row id, organization bound in the token, file size and SHA-256 re-verified before serving, `nosniff` and `sandbox` CSP; nginx GET-only, logs off, cookies and Authorization stripped.
- **Uploads:** magic-byte sniffing (client type ignored), header-only probing (no pixel decode, so no decompression bomb), per-kind limits after sniffing, server-generated storage keys, local store rejects `..` and root escapes; per-user rate limit.
- **Ads:** every query is scoped to organization **and** user; activation needs the typed phrase plus the exact budget, is serialized per user, and checks Owner caps and the active-campaign limit before any Graph call; the Owner-token fallback is Super Owner only.
- **Billing:** Stripe and Paddle signatures with timestamp tolerance; webhook event ids are idempotent (failed Stripe events retried); payment-method routes scoped to the organization; Stripe return URLs built from a setting with an allow-listed locale.
- **CSRF:** cookie-authenticated unsafe methods require a trusted `Origin` and a same-site `Sec-Fetch-Site` (`core/auth.enforce_cookie_request_origin`); bearer-token calls are not cookie-borne.
- **Mass assignment:** request models are read field by field (`payload.get(...)`/explicit attributes); no endpoint in scope copies a model dump onto an ORM row.
- **AIONEX AI plan signal:** secret re-read per request from a size-capped file, never logged; failure downgrades to `free`.
- **Synthetic load accounts:** `.invalid` e-mails plus an owner control record, owner-only password file (mode checked), cleanup touches only doubly flagged rows of one run; dry run by default.
- **Restore drill:** refuses outside the drill project, authenticates the manifest by decryption, extracts regular files only with layout, `..`, absolute-path and escape checks, `O_EXCL|O_NOFOLLOW` writes.
- **DNS TXT verification:** only `_aionex-security.<host>` is queried with a hard lifetime; IP literals refused; the public-address check still runs first.
- **Nginx:** every allowlist regex is anchored with `^...$`; unlisted API paths return 404; dot segments and encoded slashes are normalized by nginx before matching, and the raw URI reaching Starlette cannot select a different route.

## Gate triage

### Gitleaks (52 findings, all false positives)

All 52 were the `generic-api-key` entropy rule. Every line was opened at its commit and reviewed. They are listed by fingerprint in `.gitleaksignore` in four groups: G1 CI-only placeholder `SECRET_KEY` values in workflows and the Security Lab acceptance script (3); G2 SHA-256 digests and prose in docs/receipts (7); G3 a source comment and a removed sandbox smoke-test passphrase of a locally generated project (3); G4 synthetic keys, monkeypatched placeholders, idempotency/event keys and scanner bait strings in test suites (39). No real credential was found, so no rotation is required by this review.

### Semgrep (181 ERROR findings on the first run)

Counts per rule are taken from the text report of that run.

| Rule(s) | Count | Decision |
| --- | --- | --- |
| `dangerous-subprocess-use-audit`, `dangerous-subprocess-use-tainted-env-args`, `dangerous-asyncio-create-exec-audit`, `dangerous-asyncio-create-exec-tainted-env-args` | about 119 | Excluded. Audit rules flag every argv-list call. Repository-wide review: no `shell=True`, `os.system` or `os.popen` in shipped code; environments are built from fixed dictionaries (build scripts, tool runners). The taint rules for user input reaching a command stay active. |
| `avoid-sqlalchemy-text` (audit) | 3 | Excluded. All three interpolate fixed table names into `to_regclass` / migration checks; SQL-injection taint rules stay active. |
| `python/django/*` | 2 | Directory removed: no Django code; both hits were f-string LLM prompts. |
| `arbitrary-sleep`, `open-never-closed`, `useless-inner-function`, `return-in-init`, `identical-is-comparison`, `tempfile-without-flush` | about 60 | Excluded: non-security style/correctness rules; every hit reviewed as a false positive (FastAPI decorators, `defaultdict` lambdas, `psutil is None`, a file read after its `with` block). |
| `use-defused-xml` | 2 | `security_mobile.py`: fixed (FR23-05). `growth_advanced_integrations.py`: imports `xml.sax.saxutils.escape` for output escaping only; inline `nosemgrep` with that reason. |
| `react-insecure-request` | 2 | `vip-frontend/scripts/smoke-test.mjs` polls the loopback server it started; inline `nosemgrep` with that reason on both lines. |

Scope exclusions in `.semgrepignore`: dependencies/build output, test suites (fixtures and fake credentials never ship; the Security Lab acceptance fixtures are deliberately vulnerable), and documentation. Gitleaks still scans all of them.

### Trivy (first run)

31 vulnerabilities in the TripoSR manifest, 2 in `vip-frontend`, 15 in the `security-build` Go locks, and 4 DS-0002 misconfigurations. FR23-01 fixed; FR23-02 (after the image build proved Pillow 13 unresolvable with rembg), FR23-10, FR23-12 and FR23-13 documented in `.trivyignore.yaml` with statements and expiry dates.

### Dependency audit (first run)

pip-audit on the root package: cryptography 46.0.7, fixed by FR23-04.

## Residual risks

1. **Security Lab scan egress (FR23-11).** Needs a network-level egress policy for `security-scan-worker` that drops RFC 1918, loopback, link-local and metadata ranges, or a dedicated network without the data services.
2. **Scanner Go modules (FR23-10).** Expire 2026-12-31 in the gate; rebuild the five locks and re-pin `expected_binary_sha256`.
3. **TripoSR Pillow (FR23-02).** High; gate exception expires 2026-12-15. Needs a rembg release allowing Pillow 13 (or dropping rembg's Pillow cap via a reviewed fork/vendoring), then rebuild the image. Do not raise workersMax before that.
4. **Root RunPod images (FR23-12).** Expire 2027-01-31; move TripoSR to a non-root user when its image is rebuilt; Hunyuan3D stays quarantined (FR-16D).
5. **No per-user limit on Security Lab ownership verification.** Bounded by nginx per-IP limits, the per-subscriber target limits and the fixed proof path; low.
6. **Backend billing webhook body** is read before its 2 MB check; nginx caps the body at 2 MB first; low.
7. **Live verification not done here.** FR-23C (isolated DAST, authz/IDOR/upload probes against a running stack) and FR-23E (re-scan after merge and deploy) belong to the pre-launch window. This review does not claim the system is absolutely secure.

## Pre-launch register entries added

Recorded in `docs/project/COMPLETION-ROADMAP.md` under "سجل ما قبل الإطلاق": O-09 (require the FR-23 checks in branch protection), T-11 (scanner lock rebuild), T-12 (deploy vip-frontend with Next 15.5.29), T-13 (TripoSR image rebuild and non-root), T-14 (FR-23 live re-scan), T-15 (deploy the FR-23 backend and nginx fixes), T-16 (synthetic account cleanup after gate 6.1), T-17 (scan-worker egress policy).
