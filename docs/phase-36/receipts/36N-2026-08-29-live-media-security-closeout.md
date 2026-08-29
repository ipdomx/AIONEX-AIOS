# Phase 36N — 2026-08-29 Live Media & Security Closeout

## Scope
This receipt records the governed Production Studio live-media wiring and the security hardening performed in the 2026-08-29 remediation cycle.

## Live Media
- Added `/api/v1/studio/live-media` orchestration endpoints for image, video, speech, transcript, dubbing, music, and Open Song.
- User-facing Studio now exposes `/studio/live-media`.
- Provider execution remains asynchronous and durable; HTTP requests do not submit provider jobs directly.
- Admission requires tenant/project ownership, entitlement, explicit cost approval, provider/model evidence, rights/terms acceptance where applicable, idempotency, and bounded attempts.
- Open Song provider credentials remain worker-only; the backend receives no RunPod secret or raw endpoint credential.
- Open Song balance admission is performed by the secret-bearing worker before arming execution.
- Image completion rejects unknown or over-cap actual cost when an explicit user cap is present.

## Production Configuration
- Primary media execution workers are enabled in both production Compose definitions.
- Secondary Open Song remains disabled by design.
- PostgreSQL image is hardened and Redis is pinned by digest in the deployment Compose definition.
- Nginx remains non-root and production proxy boundaries remain loopback-only on the host.

## Verification
- Root project suite: 849/849 PASS.
- Backend suite: 1076/1076 PASS in the CI-equivalent isolated PostgreSQL + Redis environment.
- Ruff: PASS.
- Mypy: PASS across 248 backend source files.
- Backend verification: PASS.
- Alembic migrations: PASS through `20260825_0043`.
- Live Media integration: 7/7 PASS.
- Open Song worker tests: 10/10 PASS.
- Focused media/security contracts: 30/30 PASS.
- Frontend production build: PASS.
- npm production dependency audit: 0 known vulnerabilities.
- pip-audit runtime dependency audit: 0 known vulnerabilities across audited dependencies.
- Bandit application scan: 0 findings.
- Project security audit script: PASS.
- CodeQL Python/JavaScript: PASS in PR validation.
- Backend SBOM/vulnerability gate: PASS.
- Repository secret/hygiene gate: PASS.

## Host Security
- Fail2ban is active for SSH; repeated SSH failures are being blocked.
- SSH session protection was applied without disabling password/root login because no authorized SSH public key is currently installed; disabling password/root access would risk operator lockout.
- Android ADB service remains available only on `127.0.0.1:5556`; external Docker traffic to port 5556 is explicitly dropped. The Android application itself was not modified.
- PostgreSQL, Redis, application workers, and Ollama are not host-published.
- Project files contain no world-writable files and no project SUID/SGID files.
- Production secret files are mode 0600 and root-owned; root `/opt/AIOS/.env` was corrected to mode 0600.
- No unhealthy or restarting Production containers were present during the final host check.

## External Gates / Not Faked
The following remain fail-closed because they require external operator/business/legal material not safely inventable from the server:
- PostgreSQL credential rotation and application encryption/signing key rotation.
- AWS Bedrock credential repair (current control-plane response: 403 UnrecognizedClientException).
- Apple/Google store server credentials and release mappings.
- WhatsApp account credentials.
- Paid Professional/Business provider prices.
- Hunyuan3D commercial/legal attestation.
- Social publishing accounts/budgets/targets.
- Secondary RunPod account activation.
- iOS and Android release work.

## Security Limitation
No audit can prove the mathematical statement "no vulnerability of any kind exists." This receipt records the controls and scans actually executed and the findings actually closed. Credential rotation is intentionally not claimed as completed because the available server operator capability rejects direct credential mutation.
