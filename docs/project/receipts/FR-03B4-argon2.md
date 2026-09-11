# FR-03B4 — Argon2 compatibility candidate

Base candidate before rebase: `38b1a5b397820b26983e4ace13b9a6650254cd9e` (PR614 head; now merged into main).

This short security-maintenance batch updates only `argon2-cffi` from `23.1.0` to `25.1.0` in Backend runtime requirements. It does not alter authentication policy, Argon2 cost parameters, password migration rules, database schema, provider routing, Cloudflare, MCP, Redis, WebAuthn, Uvicorn/WebSockets, or Ruff.

Local acceptance used a fresh isolated venv with the full Backend requirements. Installed versions: `argon2-cffi=25.1.0`, `argon2-cffi-bindings=26.1.0`. A synthetic Passlib compatibility probe produced Argon2id, verified successfully, and marked a legacy PBKDF2 hash as needing update. The actual `app.core.auth.pwd_context` also produced Argon2id and verified successfully under a synthetic test-only SECRET_KEY. Runtime `pip-audit` reported no known vulnerabilities. Core suite: `956/956` PASS.

The existing Backend CI contains a database-backed contract that authenticates a legacy PBKDF2 user and verifies rehash to Argon2id. That protected Backend test suite, Docker build, SBOM/vulnerability gate, Dependency Security, CodeQL, browser boundaries and reporting checks remain mandatory before merge. No production deployment is performed by this source receipt.