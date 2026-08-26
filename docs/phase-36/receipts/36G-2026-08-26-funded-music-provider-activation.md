# Phase 36G post-closeout activation — funded music providers

Date: 2026-08-26

This activation does not reopen Phase 36. It records external-provider activation evidence against the already closed runtime boundary.

## Replicate / Google Lyria 3

The existing Production Replicate credential and funded account were used by the existing durable `audio-music-worker` path. The acceptance was explicitly bounded to the low-cost Draft route and one provider attempt.

- provider/model route: Replicate `google/lyria-3` through AIONEX `lyria-3-clip-preview`;
- max attempts: `1`;
- approved and actual cost: `$0.04`;
- generated duration: `30.0s`;
- provider MP3 checksum: `71d9b017106193e4dc543345761cd4ad4d0b8bd956850f3ff3193e47cd821844`;
- provider MP3 bytes: `663734`;
- provider state/status: `completed/completed`;
- Music Worker cycles/errors: `7/0`.

The same synthetic execution then completed the existing Production Media DAG through the already-running healthy Media Worker:

- `music` completed — MP3 checksum above;
- `cleanup` completed — WAV checksum `c446baeefad14e68530757987c3f11c8c3d7f94ab073f566f6bde2351820b6fb`;
- `master` completed — WAV checksum `3c5ca514cd54ddf2a48b19e7fa14f59eeac40be065ecc696dd1b2a8d5dd1e2f0`;
- `waveform` completed — PNG checksum `73cda46f2130497b44a88a55dd5c6baf9919fe1ffcb6d2231ba76882d9aaf57c`;
- `export` completed — WAV checksum `9869ca41c3ff0ac4f3733e6f1465ffe9453f787b68b34251fd7ebe5858759999`, `5261350` bytes;
- graph final status: `completed`.

Accordingly `valid-replicate-credential` and `lyria-preview-runtime-evidence` are satisfied. `music-rights-and-synthid-disclosure` remains an explicit policy/activation requirement and is not removed by provider funding.

## Stability AI / Stable Audio 2.5

The existing Production Stability credential and funded account were used through the same governed worker boundary.

- provider/model: Stability `stable-audio-2.5`;
- max attempts: `1`;
- approved and actual cost: `$0.20`;
- generated duration: `30.0s`;
- MP3 checksum: `5d9ff2a2fab3a072f80d9ae47722157015883e7af99dc12b3808781fec944048`;
- MP3 bytes: `497844`;
- provider state/status: `completed/completed`;
- Music Worker cycles/errors: `1/0`.

The pre-existing Phase 36G evidence already covers the governed Stable Audio local cleanup/master/waveform/export path. This fresh paid success proves that the current credential/account is funded, so `funded-stability-credential` is satisfied. `music-rights-and-ai-generated-disclosure` remains explicit.

## Cleanup and safety

After the bounded activations:

- synthetic organizations remaining: `0`;
- `AudioMusicExecution` statuses `planned/queued/running/needs_review`: `0/0/0/0`;
- no automatic retry or automatic cross-provider fallback was enabled;
- no secret value, raw provider token, raw provider job URL, or credential was emitted into the retained evidence.
