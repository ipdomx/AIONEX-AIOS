# Phase 36N receipt — FR-03B3 dependency maintenance

The candidate updates only Backend `pytz` to `2026.3.post1` and development-only `pre-commit` to `4.6.2`. No application behavior, provider activation, Cloudflare configuration, database schema, payment path, XR scope, or production runtime is changed by this source receipt.

Local evidence: full Backend requirements resolved and installed in an isolated venv, requested versions matched, runtime pip-audit returned no known vulnerabilities, pre-commit configuration validation completed without error when present, and the Core suite passed `956/956`. GitHub protected checks remain required before merge.