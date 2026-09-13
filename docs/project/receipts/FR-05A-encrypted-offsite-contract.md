# FR-05A — Encrypted off-site backup contract

Status: candidate / not deployed.

This short part establishes the client-side encryption and key-separation contract for FR-05. It does not claim that R2 uploads are encrypted yet; integration into the replicator is FR-05B.

## Decisions
- Keep the existing Cloudflare R2 private bucket and S3-compatible replication path; no Cloudflare/DNS/tunnel change.
- Require client-side authenticated encryption before any future off-site object upload.
- Envelope: AES-256-GCM, fresh 96-bit nonce per object, authenticated context (AAD), versioned magic header.
- The 256-bit data-encryption key is mounted from a separate root-owned host file, copied at container start to a 0400 runtime file, and never stored in R2 credentials, Git, backup manifests, audit details, or reports.
- Persist only a non-secret `key_id` so rotated keys can be selected for recovery. Key material remains external.
- Default policy is fail closed: off-site encryption is required when the new path is integrated.
- Existing R2 retention count remains unchanged. Key retirement must lag the oldest retained backup that references that key; deletion of old keys is not automated in FR-05A.

## Negative contracts
- Group/other-readable key files are rejected.
- Keys not exactly 256 bits (raw or strict base64) are rejected.
- Wrong keys and corrupted ciphertext fail AES-GCM authentication and leave no plaintext output.
- Encryption/decryption staging files use 0600 and exclusive creation.

## Verification
- First protected CI attempt failed only on Ruff F401 for one unused test import; corrected without changing runtime behavior.
- Focused FR-05A tests: 4 PASS.
- No production deployment, no R2 write, no live key creation, and no secret content read in this part.
