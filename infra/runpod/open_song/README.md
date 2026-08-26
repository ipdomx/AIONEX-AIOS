# Phase 36G Stage 8 — Open Song RunPod Handler

This image is the isolated GPU boundary for one governed full-song request. It produces:

- one ACE-Step song with synthetic vocals;
- four Demucs `htdemucs` stems: `vocals`, `drums`, `bass`, `other`;
- canonical 48 kHz stereo PCM WAV files only.

The AIONEX Backend remains authoritative for tenant scope, rights evidence, user approval, the `$0.20` GPU cap, one-attempt submission, provider-job reconciliation, local mix/master/waveform/export, Studio revision, and cleanup.

## Supply-chain pins

- ACE-Step source: `dce621408bee8c31b4fcf4811682eb9359e1bc94`
- Official ACE-Step linux/amd64 image: `sha256:c289cb5c0cbc60d428baa9283a49966d2fe54ecf2028fa254f99f164f3953159`
- ACE-Step base model: `e432212fec32b8965a14ffa57ae653438d6abd14`
- ACE-Step 4B language model: `0a3ec94b557aea7d508da38b31cfe7341f6ff737`
- Demucs source: `ef66d254cd6d558e207eeff2c4b8d053db2e77dd`
- `htdemucs` checkpoint SHA-256: `8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4`

The built image digest, generated SBOM digest, and handler-source digest must be inserted into the disabled AIONEX runtime binding before the Endpoint can be armed.

## Required runtime environment

- `AIONEX_HANDLER_IMAGE_DIGEST`
- `AIONEX_ARTIFACT_BRIDGE_ALLOWED_HOST` — Production value is the AIONEX public API host.

Optional:

- bounded ACE-Step/Demucs timeout values documented in `handler.py`.

The Backend supplies five short-lived, action-scoped upload grants inside the RunPod request: one for the full song and one for each required stem. Grants use HTTPS plus an `Authorization` header; tokens are never placed in URLs or persisted in the durable song execution. The handler returns only opaque artifact IDs and public audio evidence. The Backend creates fresh GET/DELETE grants, verifies the downloaded bytes, persists them to the durable Media store, then removes ingress copies. Stale ingress artifacts are TTL-purged as a fallback. No AWS/S3 credential is present in the GPU handler.

## Build

Use this directory as the Docker build context. After build, generate an SBOM and vulnerability report, push by immutable digest, create a new RunPod Endpoint with `workersMin=0`, and leave `AUDIO_SONG_LIVE_ENABLED=false` until source tests, protected CI, disabled production activation, and one explicit bounded acceptance are complete.

No automatic retry or cross-provider fallback is permitted after submission.
