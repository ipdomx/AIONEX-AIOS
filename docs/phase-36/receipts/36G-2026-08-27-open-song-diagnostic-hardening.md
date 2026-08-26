# Phase 36G — Open Song diagnostic hardening (2026-08-27)

Status: source validation only; runtime acceptance remains pending.

## Observed funded RunPod attempt

- The funded Open Song endpoint was created successfully after RunPod billing became available.
- The endpoint contract was verified with `workersMin=0`, `workersMax=1`, one 48 GB Ampere-class GPU worker, no network volume, and a 588 second execution timeout.
- One bounded provider job was submitted. It progressed through queue, worker initialization, and running, then terminated as failed.
- RunPod reported `retried=0`; AIONEX did not automatically resubmit.
- The acceptance cleanup removed the synthetic organization, audio-song execution, and media graph; verified database residue was zero.
- `song-production` therefore remains below `runtime_verified` until a complete full-song + four-stem + local render acceptance passes.

## Diagnostic hardening

The RunPod handler previously collapsed all governed runtime failures into the exception class name. This change introduces stage-specific, fixed error codes for ACE-Step startup/generation/canonicalization, Demucs separation/canonicalization, artifact bridge validation/upload, and contract failures. No prompt, lyrics, credential, endpoint identifier, local path, upload token, or provider job identifier is added to the error text.

The handler emits only a structured `open_song_failure` event with the fixed code and returns a RunPod `error` result so a failed job remains terminal and is not implicitly retried.

The AIONEX provider transport already preserves the RunPod `error` field as bounded `error_type` metadata; a regression test now verifies the stage code survives polling without exposing credentials.

## Source validation

- Open Song handler/provider tests: 27 passed.
- Ruff on changed Python files: PASS.
- Open Song Docker `source-contract` target: PASS.
- No provider generation request was made while validating this change.
- Production Cloudflare/Tunnel configuration was not changed.
- `.worktrees/` remains intentionally untouched.
