# FR-03D1 — mypy 2.3.1 candidate

Base: `c75d9d32bc29f0a30ff7dd939e2700226e81476c`

This isolated candidate upgrades the backend static type checker from mypy 1.8.0 to 2.3.1 without changing the Ruff/isort contracts. The exact Python 3.11 CI command initially exposed two real type-safety findings in `app/services/security_fabric.py`: DNS socket address values are typed as `str | int`, while the SSRF boundary only accepts textual IP addresses. The implementation now fails closed if a resolver returns a non-string address rather than merely casting it.

Local evidence:
- Python 3.11 container, mypy 2.3.1: `Success: no issues found in 262 source files`.
- Existing Ruff 0.2.0 static gate: PASS with no rules weakened.
- `tests/test_security_fabric_policy.py`: 5/5 PASS, including explicit global-string DNS acceptance and non-string DNS rejection.
- AIOS core suite: 960/960 PASS.
- `git diff --check`: PASS.

No production service, database, Cloudflare setting, MCP setting, provider, or deployment is changed by this candidate. Protected Backend/Docker/SBOM/security checks remain mandatory before merge. Runtime deployment is not required for the mypy tool pin itself; the Security Fabric source fix, if merged, will be picked up only through the normal reviewed source/deployment path.
