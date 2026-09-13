# 36N — FR-05B1 local AEAD envelope

Implemented the isolated versioned AES-256-GCM backup envelope and private keyring parser with wrong-key/tamper/AAD-swap/rotation tests. Added a direct cryptography runtime pin. No R2 wiring, production key mount, Cloudflare change or production backup behavior change in this slice.
