# Phase 36 receipt — FR-15C Stability SFX source contract

Date: 2026-10-04
Scope: FR-15C source-level audio/SFX governance only.

This receipt accompanies the FR-15C changes to the Phase 36-owned audio paths.
It records reporting coverage only; it does not promote the capability to live
provider acceptance.

The source change adds a bounded Stability Stable Audio 2.5 generate-sfx
contract with explicit 1–30 second duration, MP3 output, SFX-only semantics,
one provider attempt, and no automatic replay after an ambiguous submission.
The existing generate-music contract remains fixed at its prior duration.

The implementation keeps provider/runtime acceptance separate. No provider
credential is introduced by this receipt, no customer data is used, and no paid
or live provider request is authorized or claimed. Decoded sample-rate/channel
quality remains unclaimed until a later real-output acceptance gate.

Canonical FR-15 source receipt:
docs/project/receipts/FR-15C-sfx-quality-contract-20261003.md

Changed Phase 36-owned paths covered by this receipt:
- src/aios/audio_factory.py
- web-dashboard/backend/app/services/audio_music_providers.py
- web-dashboard/backend/app/services/audio_music_runtime.py
- web-dashboard/backend/app/services/audio_music_worker.py

The dedicated source test remains:
web-dashboard/backend/tests/test_fr15c_sfx_quality_contract.py

FR-15 remains subject to the project dependency and live-provider gates; this
receipt exists to keep the Phase 36 roadmap/reporting invariant truthful.
