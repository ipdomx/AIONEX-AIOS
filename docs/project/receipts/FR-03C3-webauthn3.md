# FR-03C3 — WebAuthn 3.0.0 candidate

Base: `fcbb83353604b9fb671a32084a32e8b918f2aa69`

This candidate upgrades the backend `webauthn` library from 2.7.0 to 3.0.0 while preserving the existing AIONEX passkey ceremony and security policy.

Local acceptance proved:
- full backend requirements install with `webauthn==3.0.0` and `pip check` PASS;
- `app.services.passkeys` imports successfully with the existing WebAuthn APIs and enums;
- registration and authentication function signatures remain compatible, including `expected_origin` accepting the configured origin list;
- generated registration options preserve platform authenticator, resident key required, user verification required, and configured timeout;
- generated authentication options preserve RP ID, user verification required, and timeout;
- passkey/social/migration plus WebAuthn 3 contract tests: 10/10 PASS;
- repository Core suite: 956/956 PASS;
- `pip-audit -r requirements-runtime.txt`: no known vulnerabilities.

No production service, database, Redis data, Cloudflare configuration, MCP setting, provider, or user credential was changed. Real database-backed passkey endpoint coverage remains mandatory in protected Backend CI before merge. Production deployment remains deferred until all accepted FR-03C runtime upgrades are merged.
