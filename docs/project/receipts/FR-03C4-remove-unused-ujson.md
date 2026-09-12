# FR-03C4 — Remove unused ujson runtime dependency

Base: `6244919e823b06098f80b973fc1e7ecb492ba4a1`

The outstanding Dependabot proposal suggested moving `ujson` from 5.13.0 to 6.0.0. Before accepting a major dependency upgrade, the production source and tests were searched for direct use. No production backend application, backend script, `src/`, or project test imports or references `ujson`; it was only an exact runtime pin and appeared in historical evidence/install metadata.

The safer change is therefore to remove the unused direct runtime dependency instead of carrying a major library with no product requirement. This reduces installed attack surface and package weight without changing the JSON contract.

Local evidence:
- full backend requirements install without `ujson`: PASS;
- `pip check`: no broken requirements;
- `ujson` is not installed transitively in the isolated environment;
- contract test proves no direct runtime pin or production Python import remains: PASS;
- standard FastAPI/Pydantic JSONResponse path serializes the representative object correctly;
- repository Core suite: 957/957 PASS;
- `pip-audit -r requirements-runtime.txt`: no known vulnerabilities.

No production service, database, Redis data, Cloudflare setting, MCP setting, provider, or user data was changed. Protected Backend/Docker/SBOM/security checks remain mandatory before merge. Production deployment remains deferred to the consolidated FR-03C rollout.
