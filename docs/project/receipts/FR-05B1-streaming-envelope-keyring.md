# FR-05B1 — Streaming encrypted envelope and keyring implementation

Status: reconciled candidate / not deployed / not wired to R2 yet.

This short part implements the locked FR-05A2 cryptographic contract without
changing Cloudflare, creating production key material, or uploading an object.
PR #656 remains the canonical Project Hub change; the stronger fail-closed
properties reviewed in alternate PR #658 were reconciled into it before merge.

## Implemented contract

- Existing BackupRecord/R2/readback/retention pipeline remains selected; restic is not introduced.
- Versioned envelope magic is `AIONEX-R2-ENC`, algorithm AES-256-GCM, nonce 12 bytes, tag 16 bytes.
- Database, platform asset snapshot, and manifest roles are processed as streams; plaintext is never whole-file buffered.
- Authenticated data binds backup ID, object role, R2 object key, envelope version, algorithm, key ID, plaintext SHA-256, and plaintext size.
- Keyring path: `/root/.config/aionex/backup-encryption/keyring.json`, mounted separately from R2 credentials and copied to `/run/aionex/backup-encryption-keyring.json` mode 0400 for the aionex user.
- Exactly one key is active; old retained keys may remain `decrypt_only`. Only the active key encrypts new artifacts.
- Reports expose lifecycle metadata only, never `key_b64` or raw key bytes.
- `cryptography==50.0.1` is a direct exact-pinned runtime dependency rather than a transitive assumption.

## Reconciled hardening

- The keyring is opened once with no-follow semantics and validated from the same file descriptor.
- Keyring symlinks, hardlinks, unsafe permissions, oversized data, duplicate JSON fields, unknown schema fields, malformed identifiers, invalid timestamps, invalid lifecycle states, and ambiguous active keys fail closed.
- Source artifacts are opened with no-follow semantics and must be single-link regular files.
- Encryption performs a second streaming evidence pass through the same descriptor; a source change during encryption aborts publication.
- Low-level writes handle partial writes, and completed artifacts are fsynced.
- Encryption and decryption stage into unpredictable mode-0600 files in the destination directory.
- Publication is atomic and no-replace: an existing destination is never overwritten.
- Decrypted plaintext is not published until GCM authentication and plaintext hash/size evidence both pass.
- Wrong key, ciphertext/header tampering, altered authenticated context, truncation, or evidence mismatch removes the private staging file and leaves no requested plaintext output.

## Verification boundary

Focused contract and adversarial tests cover round trip, retained decrypt-only
keys, secret-free reporting, unsafe keyrings and sources, duplicate fields,
existing destinations, source mutation, tampering, context mismatch, and private
staging cleanup. Protected GitHub checks are the merge authority.

FR-05B1 does **not** wire encryption into `OffsiteBackupReplicator`, upload
encrypted R2 objects, create a live keyring, deploy production, or change
Cloudflare. Those operations remain the next controlled FR-05B slice.
