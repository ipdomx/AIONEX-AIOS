# FR-03B1 — Dependabot negative-control scope

- Date: 2026-09-11 (Asia/Makassar)
- Scope: Dependabot configuration and regression tests only.
- Purpose: Keep the intentionally vulnerable security-acceptance fixture as a negative control while continuing normal backend dependency version updates.
- Change: add `exclude-paths: tests/security_acceptance_lab/fixtures/vulnerable/**` to the pip update block.
- Official configuration reference reviewed from `github/docs`: `exclude-paths` is a version-update option and patterns are relative to the configured directory.
- Existing production/runtime manifests are not excluded.
- Local tests: `956 passed`; focused contract: `3 passed`.
- PR 609/610 are version-update PRs against the intentionally vulnerable fixture and are not production dependency upgrades. They are to be closed after this guard is merged, with the reason retained.
- No deployment, provider call, secret read, Cloudflare change, MCP change, or application restart in this candidate.
