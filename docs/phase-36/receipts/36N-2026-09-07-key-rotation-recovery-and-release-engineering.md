# 36N — Key rotation recovery and release engineering

Date: 2026-09-07
Scope: expanded launch scope; AWS, Bedrock, XR and payment-provider activation are deferred to the final external-authority batch.

## Production recovery

The first file-backed secret rollout exposed a sequencing defect: the new production validator correctly rejected the historical bootstrap application key before encrypted provider/MFA material had a compatible rotation path. PostgreSQL credential rotation itself completed and verified, but the application graph was rolled back to the retained production runtime and the pre-rotation environment. PostgreSQL credentials were reconciled back to the pre-rotation credential without secret readback. Production returned to 35 Compose containers and the backend readiness endpoint returned HTTP 200. No database restore was required.

## Corrective contract

This batch adds explicit dual-key application rotation. `SECRET_KEY` is the new primary key. `SECRET_KEY_PREVIOUS` is accepted in production only from a private regular non-symlink file. Provider credential and MFA ciphertext decryption may fall back to the previous key while all new encryption uses the primary key. MFA backup-code verification also accepts hashes made with the previous key. This permits safe key rotation without making the historical key the active signing/encryption key and without invalidating existing encrypted records or backup codes.

The pre-existing private-file constraints remain fail-closed: absolute path, regular non-symlink file, no group/other permissions, non-empty content. The previous key must differ from the primary key.

## Release engineering / source debt

G29 stale Phase 36H source-only LiveKit wording is removed. The non-mutating candidate adapter now states that production provisioning belongs to the governed realtime runtime.

G28 gains `scripts/generate_production_release_manifest.py`, an authoritative manifest generator tying a release ID to the exact source commit, source-tree cleanliness, Core/Backend/Owner/Android/iOS component versions, both production Compose SHA-256 values, Alembic heads and exact running container image IDs. The production-runtime manifest is generated only after the protected merge/deployment so it records the deployed commit rather than a branch candidate.

## Verification before PR

- Python compile: PASS.
- `git diff --check`: PASS.
- Focused rotation/settings/provider/MFA tests: 26 PASS.
- Broader account-security test invocation had two database-dependent failures because the standalone local test container had no PostgreSQL service; the new rotation tests themselves passed. Protected CI remains the release gate.
