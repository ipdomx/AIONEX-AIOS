# FR-11B — Voice Transform pinned provider source contract

Date: 2026-10-04

## Scope

This source batch wires the existing governed Identity Media Voice Transform
operation to a pinned Replicate HierSpeech++ version while preserving the
existing Owner approval, identity-rights, revocation and synthetic-media
disclosure boundaries.

Provider contract verified from Replicate public model/version metadata:

- model: adirik/hierspeechpp
- version: ff5bcc71dc2c44662291fc348b9ca2eb40107c9f4b377b169fc0dea950c388c8
- content input: input_sound, WAV
- target identity voice input: target_voice, WAV
- output: one URI containing generated audio
- provider defaults retained: denoise_ratio 0, text/vector temperature 0.33,
  voice-conversion temperature 0.33, output sample rate 16000 and output-volume
  scaling disabled.

## Source behavior

- voice_transform becomes runtime-admissible only through the existing
  Identity Media access authority.
- Both content audio and target voice are persisted privately and exposed to
  the provider only through execution-scoped signed HTTPS pull URLs.
- The provider creation request uses the exact pinned version through
  /v1/predictions; latest-model drift is not accepted.
- Submission has one attempt. Timeout, transport loss and provider 5xx are
  ambiguous and are never automatically replayed.
- Current Owner/identity authorization is checked before input preflight,
  after input preflight/before provider submission, before output download and
  before final private persistence.
- Voice Transform output is validated as an audio envelope rather than falling
  through to video validation.
- Licensed-public-figure execution remains unavailable without the existing
  licensed-catalog authority. Owner approval is not treated as a likeness
  license.

## Boundaries

This batch performs no live provider request, no paid request, no credential
read, no customer-data access and no Production deployment. Tests use
httpx.MockTransport and synthetic metadata only.

The coordinator-owned VIP cross-scope change is included on the same source
branch: the user portal now collects the content WAV and target-voice WAV
separately, validates that both are present before submission, and sends the
target voice as target_voice_audio. The six portal locales carry the new labels
and validation message.
