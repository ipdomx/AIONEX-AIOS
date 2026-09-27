# Phase 36H — Revocable event stream

FR-07D1 refreshes authorization before each outbound event and during idle connections, denies the legacy anonymous broadcast in Backend, and fixes final-subscriber Redis self-cancellation. Real loopback WebSocket/PostgreSQL/Redis acceptance and limits are recorded in `docs/project/receipts/FR-07D1-live-event-stream-revocation.md`. This source receipt does not claim deployment, media-session revocation, full-host drain or final release.
