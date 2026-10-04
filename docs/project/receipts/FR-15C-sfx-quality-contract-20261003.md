# FR-15C — Stability SFX source/quality contract

Date: 2026-10-04

## Scope

This change adds a bounded source-level Stability AI Stable Audio 2.5
generate-sfx contract. It does not claim live-provider acceptance or decoded-output
quality acceptance, and the source capability is deliberately not promoted into the
legacy launch inventory.

The governed route is limited to:

- provider stability, model stable-audio-2.5, draft tier;
- operation generate-sfx;
- text input and MP3 audio output;
- explicit duration from 1 through 30 seconds;
- SFX semantics only (no lyrics and no instrumental-music semantics);
- one provider attempt only; ambiguous transport failure is not replayed;
- the existing fixed Stability request cost semantics ($0.20 / 20 credits);
- AI-generated disclosure required and no SynthID claim;
- decoded sample-rate/channel quality remains unclaimed for SFX and
  decoded_quality_measured=false.

Existing governed Stability generate-music behavior remains fixed at 30 seconds.

## Source changes

- src/aios/audio_factory.py defines the source-bound Stability SFX capability
  without adding it to AUDIO_PROVIDER_CAPABILITIES.
- web-dashboard/backend/app/services/audio_music_providers.py accepts the
  bounded SFX request, propagates explicit duration and keeps truthful output
  metadata.
- web-dashboard/backend/app/services/audio_music_runtime.py admits only the
  bounded Stability SFX route and validates duration/rights/disclosure metadata.
- web-dashboard/backend/app/services/audio_music_worker.py propagates the
  governed SFX duration and reports the source capability.
- web-dashboard/backend/tests/test_fr15c_sfx_quality_contract.py provides the
  dedicated no-live-network contract checks.

During continuation, one previously recorded unintended raw NUL byte in
audio_music_runtime.py was corrected to the intended Python escaped NUL literal
before validation.

## Validation

- Python byte-compilation for the four changed source modules plus the dedicated
  FR-15C test: PASS.
- Dedicated FR-15C pytest in an ephemeral backend-image container with
  network disabled, read-only source mount and test-only configuration: 9 passed.
- Git whitespace/error diff check: PASS.
- The dedicated provider-path test uses httpx.MockTransport; no live provider
  request is made.

## Boundaries

No provider credentials were read. No paid request, live provider call, customer
data use, production database mutation, production service change, or deployment
is claimed by this receipt. Runtime/provider acceptance and decoded-output quality
remain separate gates.
