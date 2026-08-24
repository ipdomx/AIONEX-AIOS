# Phase 36H — distributed realtime route wiring

## Scope

Replace the production API's process-local websocket notification hub with the already-tested tenant-scoped Redis Pub/Sub backplane. This source batch does not start LiveKit, Coturn, or Egress, open media ports, alter DNS/firewall/tunnel state, or claim live-media readiness.

## Implemented

- Added `app.realtime.runtime.RealtimeEventRuntime` as the API lifecycle owner for one local `DistributedRealtimeHub` backed by `RedisRealtimeBackplane`.
- API startup initializes PostgreSQL, then Redis, then the distributed realtime runtime. Shutdown stops realtime before database/Redis teardown.
- `/api/v1/realtime/connect` now registers local sockets with the distributed runtime. A backplane/subscription failure closes the accepted websocket with retryable code `1013` instead of leaving an untracked socket.
- Disconnect cleanup runs in `finally`, including non-WebSocketDisconnect failures.
- Notification fanout now publishes through the distributed runtime instead of the removed `AIRealtimeHub` singleton.
- Removed the unused process-local `AIRealtimeHub` implementation from `app.core.ai_runtime` so the production source no longer contains a second signaling authority.

## Verification

- Realtime foundation + route-wiring tests: `9/9 PASS`.
- Phase 36 governance / backend zero-dead / frontend zero-dead / market-readiness: `21/21 PASS`.
- Ruff: PASS.
- Focused Mypy: PASS.
- Existing 36H.6B evidence remains the runtime proof for real Redis Pub/Sub across four hubs: 1,000/1,000 deliveries, zero tenant leaks/duplicates/failures, node-loss recovery and zero stale subscribers.

## Truthful boundary

Production live-media activation remains blocked by external DNS/TLS/network prerequisites. No LiveKit/Coturn/Egress process, public media listener, DNS record, certificate, provider request, GPU job, or spend is created by this source change. Production deployment of the Backend route wiring is a separate post-merge gate.
