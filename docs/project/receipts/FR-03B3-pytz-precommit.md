# FR-03B3 — pytz + pre-commit compatibility candidate

Base: `94be3f6cee346fde1bd843701ec69b4febb00f76`

This short dependency batch updates only `pytz` from `2024.1` to `2026.3.post1` in Backend runtime requirements and `pre-commit` from `3.6.0` to `4.6.2` in development requirements. It does not change application source, database schema, provider routing, Uvicorn/WebSockets, Redis, WebAuthn, Argon2, or Ruff.

Local acceptance: a clean isolated venv installed the full Backend requirements; installed versions matched the requested pins; runtime `pip-audit` reported no known vulnerabilities; pre-commit configuration validation completed without error when present; Core suite `956/956` PASS. No production service was restarted or deployed by this receipt.

Protected GitHub Backend, Docker, SBOM, CodeQL, browser-boundary, dependency-security and reporting checks remain mandatory before merge. Runtime deployment, if merged, remains a separate selective rollout step.