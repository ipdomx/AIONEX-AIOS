# Phase 36N — Pre-XR Runtime Closeout — 2026-09-07

Date: 2026-09-07
Scope: `/opt/AIOS` — owned Production runtime completion before XR and later phases.

## Result

**PASS for the newly proven runtime boundaries in this receipt.**

This receipt records only evidence that was actually executed. It does not fabricate provider balances, legal rights, code-signing authority, physical-device authority, XR acceptance, or any other external fact.

## Governance deployment

- PR #559 merged through protected checks with merge commit `dbc7e050a257b4113c4dbd1b3908a41dd1ee9dad`.
- Production Backend and Owner Frontend were rebuilt from that exact merged tree.
- Post-deploy Backend and Frontend health: healthy; restart count 0.
- Production container count remained 35.
- `/owner/external-activation` returned HTTP 200.
- Unauthenticated `/api/v1/owner/external-activation` returned HTTP 401 as required.
- Pre-deploy Production DB backup ID: `40abe2e4-1044-411d-86b9-2d573388d290`.
- Backup size: 20,469,637 bytes.
- Backup SHA-256: `4de39cec0a72aeda322945b3c573606a4dfd46a75f4bfe04510a33aff872a8e5`.

## Realtime public-edge reconciliation

The authoritative Phase 36H Production receipt already proves the public media edge required by `public-stun-turn-and-sfu-capacity`:

- LiveKit/Coturn/Egress deployed with pinned images and least-privilege runtime controls.
- Independent off-host STUN/TCP 443 acceptance: PASS.
- Independent off-host LiveKit WebSocket 101 acceptance: PASS.
- Exact VIP `livekit-client@2.22.2` browser acceptance published synthetic camera and microphone: 2 tracks PASS.
- Recording acceptance subsequently completed through `EGRESS_COMPLETE` and verified Studio ingestion.

Authoritative source: `docs/phase-36/receipts/36H-2026-09-05-realtime-production-activation.md`.
SHA-256: `94cf95bbda3a97a1e6583bb5d9cc41d31339f7851871ad5aa0cde70d4fd119b2`.

This is sufficient runtime evidence for `public-stun-turn-and-sfu-capacity`; the prior external-ledger blocked state was stale bookkeeping.

## Real provider-rendered podcast acceptance

The broader `podcast-jingle-narration` capability received a real multi-speaker provider/runtime acceptance on the merged Production runtime.

### First attempt

- The first canary stopped before any provider request because the synthetic test attempted to create two Studio assets for one Studio job and correctly hit `uq_studio_asset_job`.
- Provider execution count for that failed scope: 0.
- Synthetic residue before cleanup: one job and one asset only.
- The synthetic organization was removed and verified absent before rerun.

### Accepted second run

Run ID: `20260906T2021Z`.

- Provider: OpenAI.
- Model: `gpt-4o-mini-tts-2025-12-15`.
- Provider audio submissions: exactly 2.
- Speaker 1 stock voice: `marin`.
- Speaker 2 stock voice: `cedar`.
- Each child execution: `attempts=1`, `max_attempts=1`, `provider_state=completed`, durable provider request evidence present.
- No voice clone, custom voice, or voice transformation.
- No music was included and no music-rights claim was made by this canary.
- The real persistent Production `audio-speech-worker` owned both provider boundaries; the canary did not directly invoke a provider adapter.
- Final local podcast artifact: WAV, 16.3 seconds, 3,129,644 bytes.
- Final artifact SHA-256: `bb043bd1cf7583ba2d4fd1f09d32a6c9c5a38839c16236fe807d3bdbed7b549e`.
- Independent Backend storage readback matched the same checksum and duration.
- Final artifact was deleted after readback and verified missing.
- Child media objects deleted and verified missing: 10/10.
- Synthetic DB scope after cleanup: zero.
- Active speech/transcript/dubbing/music/song/video/design/project/media queues after acceptance: all zero.
- Production container count after acceptance: 35.

Safe evidence file: `.deployment-backups/pre-xr-podcast-live-20260907/podcast-acceptance-20260906T2021Z.json`.
Safe evidence file SHA-256: `358cae32dc9b41705b453f4cff3d9224ae47f84e701f89600bd174a5a9d7b61d`.

This satisfies `provider-rendered-podcast-jingle-runtime-evidence` through a complete provider-rendered multi-speaker podcast path. Music/jingle rights remain separately governed by `music-rights-and-ai-generated-disclosure` and are not inferred from this acceptance.

## Synthetic voice disclosure source closeout in this branch

The user-facing Stock Voice paths are being hardened so Speech and Dubbing requests require an explicit `synthetic_voice_disclosure_accepted=true` value in the API request and a visible acknowledgement checkbox in the Studio UI. The API type is fail-closed (`Literal[True]`) and the acceptance is audit-logged.

This source change must pass CI, merge, and deploy before `synthetic-voice-disclosure` can be reconciled to runtime-satisfied. Until that post-merge deployment exists, this receipt does **not** mark that gate satisfied.

## External facts intentionally not fabricated

The following remain external-authority boundaries rather than unfinished local coding:

- exact numeric provider balances/thresholds where the Owner has chosen private funding attestation instead of numeric balance management;
- voice-owner rights/consent for transformation or cloning;
- music rights/provider terms/disclosure evidence for applicable generated music uses;
- platform code-signing authority;
- physical-device or blockchain deployment authority;
- XR device validation and everything after the Owner-defined XR cutoff.
