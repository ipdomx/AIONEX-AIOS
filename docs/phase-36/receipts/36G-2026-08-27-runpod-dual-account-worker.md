# Phase 36G — RunPod dual-account worker preparation (2026-08-27)

Status: source validated; secondary account is prepared but not armed.

## Purpose

A second Open Song worker is defined for an independently funded RunPod account. The primary and secondary workers consume the same durable AIONEX audio-song queue, but each worker mounts a different server-side RunPod secret file and uses a different worker identity. This allows two funded accounts/endpoints to process separate executions concurrently without sharing credentials.

## Safety properties

- Primary secret: `web-dashboard/secrets/RUNPOD_GPU.env`.
- Secondary secret: `web-dashboard/secrets/RUNPOD_GPU_SECONDARY.env` (operator-managed, ignored by Git, not provisioned by this source change).
- The secondary service is isolated behind the `audio-execution-secondary` Compose profile.
- `AUDIO_SONG_LIVE_ENABLED=false` remains the default for both workers until runtime acceptance and explicit activation.
- Both workers retain `max_attempts=1`; there is no automatic cross-account resubmit after a provider submission boundary.
- Both workers use the same durable PostgreSQL claim/fencing controls and media object store, so one execution can be leased to only one worker at a time.
- No RunPod API key, endpoint ID, or other credential is committed to Git.
- Cloudflare/Tunnel configuration is unchanged.

## Validation

- Targeted production Compose contract tests: 2 passed.
- Production Compose `config --quiet` with `audio-execution-secondary` profile: PASS for both production Compose definitions.
- The secondary account remains unarmed until its server-side API key and accepted Open Song endpoint binding exist.
