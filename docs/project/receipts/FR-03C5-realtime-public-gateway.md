# FR-03C5 — Authenticated public Realtime gateway

Final FR-03C live acceptance found that the upgraded Backend was healthy and the realtime route returned HTTP 200 internally, while the public API gateway returned HTTP 404 for both `/api/v1/realtime/status` and the `/api/v1/realtime/connect` WebSocket handshake. The defect is therefore in the Nginx allowlist, not Uvicorn/WebSockets.

This change exposes only the documented distributed realtime routes. `/api/v1/realtime/status` receives the normal public API limits and auth-channel marker. `/api/v1/realtime/connect` receives WebSocket Upgrade/Connection forwarding, buffering disabled, bounded connection concurrency, long read timeout, and `X-AIOS-Auth-Channel: public`. Because the access token is carried in the query string by the existing endpoint contract, access logging is disabled and the error log is suppressed for this exact route so the token is not persisted by Nginx.

The legacy process-local `/ws/{client_id}` endpoint is not referenced by tracked application frontend source; only a historical Next rewrite exists. The public API gateway therefore changes `/ws/` from a proxy to HTTP 404, while the private frontend rewrite itself is left unchanged.

Acceptance before PR: candidate Nginx configuration passes `nginx -t` with the same tmpfs ownership model as production; focused gateway and portal-boundary tests pass 7/7. No production reload is performed by this receipt.
