# Phase 36I.2 — local executable 2D animation/game runtime

Status: **locally executed; provider-free**.

- Added a deterministic, traversal-safe `TwoDProjectBuilder` for `2d-animation` and `2d-game` targets. It materializes self-contained HTML/JavaScript, a game control manifest where applicable, SHA-256 artifact evidence, an organization fingerprint rather than raw tenant identity, and rejects non-empty/escaping destinations.
- The generated runtime contains no provider/network client and records `provider_requests=0` and `external_spend_usd=0.0`.
- Headless Chromium executed both outputs from local files. The animation advanced from frame 2/x=46 to frame 13/x=79. The game advanced from frame 2 to frame 18; ArrowRight moved x=80→92 and Space changed score 0→1. Both had one canvas, zero external requests and zero console errors.
- Chromium also recorded a real 1.72-second 800×500 VP8 WebM preview after the animation reached frame 90. The file is 16,493 bytes with SHA-256 `fc687cd42ea188e779e73accd64afde61a3084a381d2a36aaa75f6e1a0c19b3d`; the production media-worker FFprobe validated codec/dimensions/duration in a no-network, read-only one-shot.
- Runtime evidence is archived under `/opt/AIOS/.deployment-backups/phase36i-part2/20260824T204806Z/`. The browser evidence SHA-256 is `276ee7fd6996f65b6719819f77b286117ea4055e2ba0717df444a192b20d355c` and build evidence SHA-256 is `c11522ba5917aecde9b5ad24d17ac0a1567ee9f0084e44d0467fe606350f38d6`.
- The existing `two-d-animation-games` maturity remains `locally_executed`; this batch does not claim a provider-backed renderer, mobile-store packaging, or production deployment.
- The existing `ai.vip-e.net` Cloudflare application tunnel remains useful for later HTTPS delivery of browser artifacts. No tunnel configuration, DNS, firewall, production container, database, provider or GPU resource was mutated by this acceptance.
