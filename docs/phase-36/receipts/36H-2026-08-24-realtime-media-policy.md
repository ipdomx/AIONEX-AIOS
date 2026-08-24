# Phase 36H Part 4 — Calls, Screen Share and Adaptive Media Policy

Updated: 2026-08-24T14:08:17Z

## Scope completed

- Added a provider-neutral, network-free `RealtimeMediaPolicy` over the durable admission and SFU room-plan authorities.
- Deterministically classifies 1:1 vs group calls from admitted participant count.
- Enforces admission-grant parity for publish, subscribe and screen-share authority.
- Defines microphone, camera and screen-share publication plans without provisioning a provider room.
- Adds bounded camera and screen-share simulcast profiles (`q/h/f`) plus adaptive-stream and dynacast flags.
- Keeps recording explicitly disabled in every Part 4 call plan.
- Adds deterministic quality decisions from packet loss, jitter, RTT and available outgoing bitrate with hysteresis, one-layer downshift/recovery, and no network side effect.
- Safe snapshots expose no raw tenant IDs, room IDs, provider credentials or grant material.

## Local validation

- Part 4 media policy + Part 3 SFU/TURN tests: `22/22 PASS`.
- Phase 36 governance + zero-dead + market-readiness: `18/18 PASS`.
- Phase 36 backend capability snapshot: `1/1 PASS`.
- Ruff: PASS.
- Focused Mypy: PASS.
- `git diff --check`: PASS before PR.

## Validation incidents recorded truthfully

1. The first Part 4 pytest invocation used a synthetic test `SECRET_KEY` shorter than the repository minimum. Collection stopped before tests ran. The command was repeated with a longer synthetic non-production key and passed.
2. A later capability test was invoked from repository root and inherited the legacy root `.env` value for `AIOS_TELEGRAM_ALLOWED_USERS`, which is not JSON-compatible for current Settings parsing. The same test was repeated from `web-dashboard/backend` with an explicit isolated test environment and passed. No production settings or secrets were changed.

## Explicit non-claims / not completed

- No LiveKit/Coturn process was started.
- No SFU/TURN/STUN provider credential was validated or consumed.
- No production database migration `0040/0041` was applied.
- No production API/WebSocket signaling route was rewired.
- No host media port, firewall, DNS or tunnel rule was changed.
- No actual camera/microphone/screen-share packet traversed an SFU.
- No adaptive bitrate decision was applied to a live track.
- No Egress/recording or Creative Studio ingestion was implemented in Part 4.
- No 1000-user media load, failover or recovery claim is made.
- Provider requests: 0. GPU jobs: 0. Provider spend: $0.00.

## Rollback

Part 4 is source-only. Rollback is a source revert; it does not require a database restore, service restart, network rollback or provider cleanup.
