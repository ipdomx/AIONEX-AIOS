# Phase 36N — Comprehensive pre-launch closeout — 2026-08-30

## Scope

Full server/project review after IPMI recovery: host hardening, Docker/runtime cleanup, production health, provider/model truth, media readiness, Security Lab/ZAP acceptance, source scanners, and pre-launch fail-closed controls. No paid media/provider execution was armed.

## Server and cleanup evidence

- Ubuntu 24.04.4 LTS packages were upgraded to the current repository state; no packages remained upgradable and no failed systemd units remained.
- UFW was recovered only after verifying the required netfilter modules. It is active with default deny incoming/default allow outgoing and rate-limited SSH 22 for IPv4/IPv6. Application origins remain loopback-only and are reached through the existing outbound Cloudflare tunnel.
- Fail2ban SSH jail remains active. SSH keeps the previously documented operator-access exception (`PermitRootLogin=yes`, password authentication enabled) because no replacement public key is installed; it must not be disabled blindly.
- Docker cleanup preserved every image referenced by a container plus the accepted Open Song image, the retained backend rollback, current hardened candidates, Ollama and the deferred Android image. 225 unreferenced images, 34 anonymous test volumes and reproducible build cache were removed. Root filesystem usage fell from about 546 GB used to about 253 GB used.
- The retained Qwen/Ollama model volume and deferred Android container were not deleted.

## Production runtime truth

- API OpenAPI contract: 498 paths / 600 operations. All 177 static GET routes were exercised without a 404 or 5xx response.
- Public site and portal return HTTP 200; Owner ingress returns the expected Cloudflare Access redirect; API `/ready` returns HTTP 200.
- All active production containers are healthy; no active container is unhealthy or restarting.
- Media workers that previously failed S3 preflight now use the private durable local media volume while pre-launch paid execution remains disabled. Speech, transcript, dubbing, music, song, video, image, image-derivative and general media workers all pass health checks with local storage.
- Persistent paid/live flags remain false. Secondary RunPod remains owner-deferred and was not touched.
- AWS credentials fail STS identity validation and the durable AWS provider record is therefore `error` + disabled. Azure OpenAI identity/endpoint health succeeded and is recorded connected. All other configured provider health probes succeeded or truthfully reported configuration/catalog-only status.
- Launch model evidence for OpenAI, Mistral, DeepSeek and Ollama was refreshed from live provider inventory without generation/spend.

## Security Lab repair and acceptance

The Security Lab had two real runtime defects discovered by this review:

1. `security_tool_cache_data` was root-owned, so the non-root scanner could not write Semgrep/Trivy/Grype/Gitleaks caches.
2. OWASP ZAP was not wired to the scanner in production, and its read-only runtime lacked writable Java/Firefox/session paths. The original 256 MiB ZAP session tmpfs also exhausted its HSQLDB storage while spidering the public site.

Remediation in this change:

- durable one-shot cache initializer with only `CHOWN` + `DAC_OVERRIDE`, no network, then non-root/read-only scanner runtime;
- writable durable scanner cache and `TMPDIR` outside the 64 MiB `/tmp` tmpfs;
- production internal `SECURITY_ZAP_URL=http://security-zap:8080` default;
- ZAP remains read-only with bounded writable `.ZAP`, `.java`, `.mozilla` and `/tmp` tmpfs paths;
- ZAP heap is explicitly capped at 1024 MiB and container memory at 3 GiB;
- source-tool adapter parses complete JSON before diagnostic truncation, preventing large Bandit/Trivy reports from silently losing findings;
- Gitleaks emits JSON through `/dev/stdout` so findings are normalized correctly;
- the isolated security acceptance runner now generates ephemeral test secrets, uses durable scanner temp/cache space, and applies the same bounded ZAP runtime hardening.

The isolated Security Acceptance Lab completed `PASS`: production was not modified, no external target or DNS was used, the vulnerable fixture was correctly blocked, the remediation cycle passed, the final release gate passed, deterministic repeatability passed, behavioral vulnerable/fixed assertions passed, the learning rule was promoted, and durable database evidence was verified. Its tool matrix exercised AIONEX web/API/source/mobile scanners plus Semgrep, Bandit, Trivy, OSV-Scanner, Grype, TruffleHog, Gitleaks, Syft, Katana, ProjectDiscovery HTTPX, Nuclei, OWASP ZAP, Nmap and Nikto. Intrusive scenario-specific adapters remain fail-closed unless an authorized isolated clone scenario is supplied.

A live passive ZAP crawl of `vip-e.net` completed after the ZAP repairs. It reported no high/critical alert. The repeated actionable classes were CSP `unsafe-inline` for script/style and missing HSTS; large locale redirects were also reported as low-risk redirect heuristics. HSTS is added to the AIOS Nginx origins and VIP frontend source in this change. CSP nonces/hashes cannot be removed blindly because the current Next.js/Firebase/Google flows use inline bootstrap/style behavior; this remains a browser-runtime hardening gate rather than being falsely marked fixed.

## Source security review

- Full tracked-source scans now execute rather than failing from cache/tmpfs defects.
- Semgrep: no findings in the reviewed source snapshot.
- Bandit high findings were confined to the deliberately vulnerable Security Acceptance fixture; the production-filtered snapshot had no high/critical Bandit finding.
- Trivy/Grype dependency findings in the tracked-source snapshot were confined primarily to the deliberately vulnerable acceptance fixture. Production-filtered Grype reported zero vulnerabilities. A subsequent exact runtime-image audit is recorded below because tracked-source scanning alone was not sufficient to certify the retained GPU images.
- TruffleHog/Gitleaks production-source hits were reviewed as test/reference strings or synthetic credentials, not returned production credentials. The GitHub repository secret/hygiene gate remains authoritative and passes.
- Open Song apt upgrade now explicitly uses `--no-install-recommends`.

## Residual external/operator gates — not falsified

- AWS credentials/S3 authority must be replaced or repaired before S3-dependent 3D storage can be enabled. AWS stays disabled.
- Realtime LiveKit/Coturn remains the deliberate Phase 36H external activation gate; source-only candidate infrastructure is not represented as live.
- 3D commercial/legal attestations and live storage/provider gates remain external requirements.
- Stripe live foundation is retained, but paid product price mappings are not invented. Apple/Google store credentials/signing remain external store gates.
- Root/password SSH cannot be retired until a trusted public-key login is installed and tested.
- Production `SECRET_KEY` and PostgreSQL credential rotation remain controlled migrations because blind rotation can destroy encrypted-data access or lock out the service.
- Secondary RunPod and mobile application work remain deferred to the separately authorized final stage.


## 2026-08-31 closeout continuation — exact GPU image audit

The retained GPU images were scanned by exact local image identity with Trivy `0.73.0`; raw JSON is kept outside Git under `.deployment-backups/phase36n-comprehensive-closeout/20260831T005725Z/` and the small source-controlled summary is `docs/phase-36/evidence/36N-2026-08-31-comprehensive-closeout-summary.json` (SHA-256 `6eadc40ffb314b03970dfa546a74229e397f722002ffa8afe924786ea432f0c7`).

- **TripoSR** `ipdomx/aionex-triposr:phase34f-final-v1`: `0 Critical / 0 High`, `31 Medium / 32 Low`; runtime security decision remains approved.
- **Open Song** `ipdomx/aionex-open-song:f8259d5`: `0 Critical / 12 High`. The seven unique advisory IDs represented by those 12 package findings are all explicitly covered by the source-controlled `infra/runpod/open_song/openvex.json`. The VEX reasons are runtime-specific (for example Gradio UI code is not launched and model-loading advisories are constrained by baked, revision-pinned, offline assets). No blind major-version upgrade was applied because it would invalidate the accepted ACE-Step runtime without a separate GPU re-acceptance.
- **Hunyuan3D production v11** exact digest `sha256:34bd37c577a8c769005a11f94bf4658d0b9f31d52df5c75e2a8f01a5ed8499dc`: `33 Critical / 590 High`. Most OS findings come from the old RunPod development base (`linux-libc-dev` alone accounts for `501` High/Critical findings), but the active `/opt/hunyuan-venv` itself still intersects `35` High/Critical findings, including one Critical `torch 2.5.1+cu124`, one Critical plus two High `pytorch-lightning 1.9.5`, and High findings in Pillow, Transformers, Cryptography, Gradio, Starlette, Diffusers and Protobuf. Because the active inference environment is affected, the image is **not** accepted by VEX or by “unused build package” reasoning.
- The source now fails Hunyuan closed through `HUNYUAN_RUNTIME_SECURITY_APPROVED=False`; the exact quarantined digest is exposed in the Owner 3D security snapshot, and `provider_runtime_configured("hunyuan3d")` returns false before any provider submission. TripoSR remains the approved fallback. Hunyuan can only be re-enabled after a new hardened GPU image earns both security acceptance and the original functional/PBR regression acceptance.
- The older local `phase34c-pbr-v4` image was also confirmed to contain the same `33 Critical / 590 High` class and is not a Production authority.

This corrects the earlier broad “GPU hardening observations” wording: the exact production Hunyuan v11 image has a real technical security gate and is deliberately quarantined rather than being represented as launch-ready.

## 2026-08-31 Batch 2 — Backend/API, database, workers and UI regression

A fresh isolated PostgreSQL 16 + Redis 7 harness was migrated from an empty database through Alembic `20260825_0043`. A child-process import defect in the Phase 36B 1000-tenant admission acceptance was fixed by explicitly adding the Backend root to the child test process `sys.path`; the 1000-admission test then passed without lost or duplicate durable work.

Final regression evidence on the closeout source snapshot:

- Backend: **1080 passed, 1 skipped, 0 failed** in `241.11s` on disposable PostgreSQL/Redis; migrations through `0043` succeeded.
- AIOS Core: **849 passed, 0 failed**.
- Owner frontend: TypeScript PASS; ESLint PASS with zero warnings/errors; Owner Arabic coverage PASS (`991` translatable UI strings and `5` approved technical tokens); Next.js Production build PASS with `90` routes; runtime `npm audit --omit=dev` reports `0 High / 0 Critical`.
- VIP frontend: integrity PASS (`96` files, `6` complete locales, no simulated-data markers); TypeScript/ESLint PASS; static Production build PASS with `127` routes; static smoke PASS for `94` URLs/PWA/deployment headers; runtime `npm audit --omit=dev` reports `0 High / 0 Critical`.
- Both Production Compose definitions parse successfully after the Security Lab/ZAP and local-media changes.
- A new isolated Security Acceptance Lab run completed **PASS** with `production_modified=false`, `external_target_used=false`, required detection coverage `1.0`, `138` vulnerable-fixture findings, no unexpected engine failures, behavioral validation PASS, deterministic repeatability PASS, learning rule `promoted`, remediation `verified_fixed`, and final release gate `passed`. Report SHA-256: `3a4e1ca2a8b1b8641881f88d6988d0e648fdd995d2127376497cce0af3357151`.

No provider generation, paid GPU execution, Production database mutation, or destructive Production chaos was performed by this continuation.

## Updated closeout boundary

The internal Backend/API/database/worker/frontend/security regression boundary is green. Hunyuan3D v11 is intentionally **security-quarantined**, not silently accepted. Remaining external/operator gates listed above stay explicit; none are converted into fake completion by this closeout.
