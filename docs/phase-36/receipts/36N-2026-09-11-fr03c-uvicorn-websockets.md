# 36N / FR-03C1 — Uvicorn + WebSockets transport compatibility

The live backend dependency pair was upgraded together to Uvicorn 0.52.4 and WebSockets 17.1. This avoids the resolver conflict seen when Uvicorn was upgraded while WebSockets remained 12.0.

Production protocol selection remains `auto`. Under the upgraded pair, Uvicorn resolves to its SansIO WebSockets implementation. A real local Uvicorn server using the project's `/realtime/connect` route completed synthetic authenticated connect, connected-event delivery, ping/pong, and disconnect. Realtime wiring tests, Core tests, resolver checks, and dependency audit passed locally.

No production mutation is authorized by this receipt. Merge and selective rollout remain gated by protected GitHub checks.
