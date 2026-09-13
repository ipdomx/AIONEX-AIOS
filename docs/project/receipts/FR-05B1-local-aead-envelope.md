# FR-05B1 — Local AEAD envelope implementation

Scope: implement and prove the versioned client-side encryption primitive before wiring any R2 transport or production setting.

Implemented locally:
- Direct runtime pin: `cryptography==50.0.1` (no reliance on `PyJWT[crypto]` transitively).
- Versioned `AIONEX-R2-ENC` envelope using streaming AES-256-GCM with 32-byte key, random 12-byte nonce and 16-byte authentication tag.
- Canonical AEAD associated data binds backup ID, object role, R2 object key, key ID, envelope version/algorithm and plaintext SHA-256/size.
- Root-only JSON keyring parser rejects symlinks, hardlinks, group/world permissions, duplicate fields, invalid key size/state and invalid active-key topology.
- Active key encrypts new objects; decrypt-only keys can restore retained generations after rotation.
- Decryption writes only to a private temporary file and publishes the requested destination only after GCM authentication plus plaintext SHA-256/size verification.
- Wrong-key, ciphertext tamper and object-key swap all fail closed and leave no accepted plaintext output or partial file.

This slice intentionally does **not** import the encryption module from `offsite_backup.py`, add production key mounts, upload ciphertext to R2, or change Cloudflare. Those are later FR-05B/FR-05C slices.
