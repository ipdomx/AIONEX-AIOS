# FR-03C2 — redis-py 8.1.0 candidate

Base: `417f3a8394dd2befcdb31c7b34a4e965ae6989b4`

This candidate upgrades the Python Redis client from `redis==5.0.0` to `redis==8.1.0` while keeping the production Redis server architecture unchanged.

Local acceptance used a separate ephemeral Redis 8 container with no production data. It proved:
- redis-py 8.1.0 installs with the full backend requirements and `pip check` reports no broken requirements;
- ping and connection lifecycle through `redis.asyncio`;
- the real project-execution admission Lua acquire/release scripts, including saturation and release/reacquire behavior;
- real Pub/Sub through `RedisRealtimeBackplane`, including subscribe, publish, delivery, unsubscribe, and async close;
- focused Redis/realtime/auth tests: 18/18 PASS;
- repository Core suite: 956/956 PASS;
- `pip-audit -r requirements-runtime.txt`: no known vulnerabilities.

Additional local DB-backed tests were intentionally not counted because PostgreSQL was not started in the isolated local acceptance; protected Backend CI remains responsible for those database-backed tests. The ephemeral Redis container was removed after acceptance.

No production Redis data, production service, database, Cloudflare setting, MCP setting, or provider was changed by this candidate. Deployment remains deferred until all accepted FR-03C runtime upgrades are merged, to avoid repeated production restarts.
