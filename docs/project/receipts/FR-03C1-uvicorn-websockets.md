# FR-03C1 — Uvicorn + WebSockets compatibility candidate

Base: `3746845a617769293800de0b6b6070d9e94ca574`

This candidate upgrades the live backend runtime pair together:
- `uvicorn[standard]` 0.27.0 -> 0.52.4
- `websockets` 12.0 -> 17.1

The pair is intentionally reviewed together because Uvicorn 0.52.4 requires WebSockets >=13 when the standard extra is installed. Production `main.py` leaves WebSocket protocol selection at Uvicorn's default `auto`; with this candidate, Uvicorn 0.52.4 resolves that to `WebSocketsSansIOProtocol`, avoiding the deprecated legacy WebSockets implementation.

Local evidence:
- exact backend dependency installation PASS; `pip check` reports no broken requirements;
- real Uvicorn transport acceptance on the project `/realtime/connect` endpoint PASS: authenticated synthetic connect, connected event, ping/pong, disconnect;
- protocol selection asserted as `uvicorn.protocols.websockets.websockets_sansio_impl.WebSocketsSansIOProtocol`;
- realtime wiring tests plus transport test: 4/4 PASS;
- repository Core suite in its canonical environment: 956/956 PASS;
- `pip-audit -r requirements-runtime.txt`: no known vulnerabilities.

No production service, database, Cloudflare setting, MCP setting, or provider was changed by this candidate. Protected Backend/Docker/SBOM/security checks remain mandatory before merge. Production deployment is a separate selective rollout after exact-merge image acceptance.
