# Phase 36F — Governed High-Resolution Final Export Runtime Acceptance

Date: 2026-08-26
Status: **PASS — `video-final-export` runtime verified within the local governed export boundary**

## Purpose

This receipt closes the remaining internal Phase 36F final-export evidence gap without widening the provider-generation claim. Historical 36F evidence intentionally kept `video-final-export=source_built` because the accepted provider-generation path produced 720p source video. This acceptance verifies the separate governed **final export/render** path at the advertised output profiles.

## Runtime used

- Production Media Worker image family: `aionex-aios-media-worker:local`.
- Runtime adapter: `app.services.media_ffmpeg.FFmpegRuntime`.
- FFmpeg/FFprobe target: **9.0**.
- Hardware policy: software encoder only.
- Network: **none**.
- Provider requests: **0**.
- Provider spend: **$0.00**.
- Test artifacts existed only inside a disposable container and were removed automatically.

FFmpeg preflight verified the governed encoder/filter contract including `libx264`, `aac`, `libsvtav1`, `libopus`, `chromakey`, `overlay`, and the required audio filters.

## Accepted output profiles

The same `FFmpegRuntime.render(operation="render_scene", profile_id="video-mp4-h264")` path used by the Media DAG rendered short deterministic H.264/AAC MP4 outputs. `FFmpegRuntime.qa_output` then verified stream presence, H.264 codec, AAC codec, exact width, exact height, and positive duration.

| Profile | Dimensions | Bytes | Output SHA-256 | Command hash | QA |
| --- | ---: | ---: | --- | --- | --- |
| 1080p | 1920×1080 | 7,421 | `cc03c889b137535b1cbaf7ad9c58d2dbd83583b6d9fd607e817eb921025e369a` | `a4a322f8ceee38493f7a0b06c68a4405ab0bc45834f58163aaedc8485c87162f` | PASS |
| 1440p | 2560×1440 | 7,935 | `dde7d00a8ff027bfa07b08280b87a4aaa02f793d01356ac9e34c7c782dc1b883` | `9636fdcc32fc9f12f8acd54ca98fe825f361ed5a47b6b9f4f42bff497bd2ef75` | PASS |
| 4K | 3840×2160 | 9,399 | `7782578e2942e10fef742c8dbfef4d930474589787cb47fb37e3b53a0a2ec2bf` | `7d804d712de4208914680809e78c4889a085f700f7ab47df6963b98411eeb58c` | PASS |

All three outputs reported `duration_seconds=0.25` and every governed QA check returned `true`.

## Claim boundary

This acceptance proves the local governed **final export** path can encode and validate 1080p, 1440p, and 4K outputs. It does **not** claim that every external video provider natively generates those resolutions, and it does not claim perceptual super-resolution quality when a lower-resolution source is scaled or re-rendered.

Final registry decision: `video-final-export=runtime_verified`.
