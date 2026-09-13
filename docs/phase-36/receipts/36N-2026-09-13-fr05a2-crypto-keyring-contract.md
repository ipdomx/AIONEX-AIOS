# 36N — FR-05A2 crypto/keyring contract

Locked the exact client-side R2 encryption design: existing backup pipeline + streaming AES-256-GCM envelope, separate root-only keyring, decrypt-only rotation generations, encrypted manifest, and explicit FR-06 boundary for local-at-rest/full-disk encryption. No runtime or Cloudflare change.
