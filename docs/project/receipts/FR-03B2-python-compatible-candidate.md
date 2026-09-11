# FR-03B2 — Python compatible dependency candidate

Date: 2026-09-11
Base: `77f3b243e1b8507a631c021226ed95ed0626fcbc`

This candidate applies the current Dependabot Python-runtime minor/patch group except the Uvicorn update that is incompatible with the retained `websockets==12.0` boundary. Uvicorn remains `0.27.0`; the WebSockets/Uvicorn compatibility migration stays in FR-03C as a separate major-upgrade acceptance.

Included updates: FastAPI, Pydantic, pydantic-settings, SQLAlchemy, Alembic, psycopg2-binary, Celery, HTTPX, boto3, python-socketio, Strawberry GraphQL, python-dotenv, phonenumbers, python-dateutil, orjson, prometheus-client, loguru, and Selenium. The existing project-worker contract was updated only to the reviewed Selenium `4.48.0` pin.

Local evidence:
- Python resolver: production runtime requirements PASS.
- Python resolver: full backend requirements PASS.
- Root Core suite: `956 passed in 40.69s`.
- Project-worker contract target: `6 passed`.
- Selenium contract coverage: both root project-worker and backend project-execution contracts updated to `4.48.0` and targeted tests PASS.
- `pip-audit -r requirements-runtime.txt`: no known vulnerabilities.
- `git diff --check`: required before commit.

No production service, database, Cloudflare configuration, MCP configuration, provider, or shared-hosting release is changed by this candidate. Backend/Docker/SBOM/security CI remain mandatory before merge. Runtime deployment, if merged, is a separate selective deployment step.


Ruff remains pinned at `0.2.0` in this batch. The proposed `0.16.6` update changes the repository lint contract (new I001/B008/BLE001/UP045 and related findings across existing code) and failed the protected Backend static-quality gate. That tool upgrade is deferred to an isolated lint-migration subpart; no lint gate is weakened here.
