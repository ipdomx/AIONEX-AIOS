# FR-05B2 — Encrypted OffsiteBackupReplicator/R2 wiring

Status: source candidate; protected PR and merge required; not deployed.

## Implemented

- Off-site enablement now fails closed unless client-side encryption is required and a valid private keyring loads.
- Every new database dump, complete platform-asset snapshot, and manifest is encrypted before upload.
- New object names follow the locked contract: `database.dump.aex1`, `platform-assets.tar.aex1`, and `manifest.json.aex1`.
- Full R2 ciphertext readback verifies byte count, SHA-256, envelope version, algorithm, and non-secret key identifier metadata.
- Durable evidence preserves plaintext checksum/size for the existing restore pipeline while separately recording authenticated ciphertext evidence.
- Restore validation downloads ciphertext into private staging, verifies it, authenticates/decrypts it with backup ID, object role, and exact R2 key bound as AAD, then publishes plaintext only after all evidence matches.
- Wrong keys, corruption, unknown evidence schemas, unexpected object keys, or existing destinations fail closed and remove staging output.
- Explicit schema-v1 legacy restore compatibility remains available only for already-retained plaintext generations; new replication cannot create plaintext objects.
- Retention recognizes encrypted and legacy complete-manifest anchors and deduplicates backup prefixes.
- Fixed the restore worker to validate the downloaded platform-asset snapshot path instead of incorrectly passing the downloaded database path.

## Verification

- Focused encryption/offsite/backup executor suite: 62 passed, 1 skipped.
- FR-05 focused subset: 22 passed.
- Ruff: pass.
- Mypy for the changed services: pass.
- Python compilation and Git diff whitespace validation: pass.
- No production keyring was created, no R2 object was uploaded, and no application, worker, Cloudflare, or production configuration was changed.

## Boundary and next gate

FR-05B2 is source wiring only. FR-05C must not deploy until the operator-owned production keyring and its independent recovery copy exist, the rollout/rollback plan is recorded, and a controlled encrypted upload/readback/restore canary is approved. Local volume encryption remains FR-06.
