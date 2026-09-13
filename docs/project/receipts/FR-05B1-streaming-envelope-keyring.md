# FR-05B1 — Streaming encrypted envelope and keyring implementation

Status: candidate / not deployed / not wired to R2 yet.

This short part implements the already-locked FR-05A2 cryptographic contract without changing Cloudflare or uploading any object.

- Existing BackupRecord/R2/readback/retention pipeline remains selected; restic is not introduced.
- Versioned envelope magic is `AIONEX-R2-ENC`, algorithm AES-256-GCM, nonce 12 bytes, tag 16 bytes.
- Database/assets are processed as streams; plaintext is never whole-file buffered.
- Authenticated data binds backup ID, object role, R2 object key, envelope version, algorithm, key ID, plaintext SHA-256 and size.
- Keyring path: `/root/.config/aionex/backup-encryption/keyring.json`, mounted separately from R2 credentials and copied to `/run/aionex/backup-encryption-keyring.json` mode 0400 for the aionex user.
- Exactly one key is active; old retained keys may remain `decrypt_only`. Only the active key encrypts new artifacts.
- Reports expose lifecycle metadata only, never `key_b64` or raw key bytes.
- Wrong key, tampering, or altered authenticated context fails closed and removes partial plaintext output.
- `cryptography` is now a direct exact-pinned runtime dependency rather than relying on the PyJWT extra transitively.

FR-05B1 does **not** wire encryption into `OffsiteBackupReplicator`, upload encrypted R2 objects, create a live keyring, or deploy production. That is the next short FR-05B slice.
