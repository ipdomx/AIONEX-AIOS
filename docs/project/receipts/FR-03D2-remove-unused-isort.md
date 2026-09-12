# FR-03D2 — remove unused isort development dependency

Base: `67c15e0de4c32c183bb94819b7f9f500978fbfd9`

The Dependabot proposal to upgrade isort 5.13.0 to 9.0.1 was reviewed instead of merged blindly. A read-only isort 9.0.1 check against `app` and `tests` produced 8,846 lines of formatting diff across hundreds of files when run with default behavior. Repository usage review found no pre-commit hook, CI/static-quality invocation, script, or automation that invokes isort; the only functional tracked reference was the backend development dependency pin itself.

The safer change is therefore to remove the unused tool rather than introduce a mass import-format migration with no release value.

Acceptance:
- Python 3.11 full backend requirements install succeeds with `isort_present=false`.
- Existing Ruff static-quality gate: PASS.
- mypy 2.3.1: `Success: no issues found in 262 source files`.
- Dependency/automation contract: 2/2 PASS.
- AIOS core suite: 962/962 PASS.
- `git diff --check`: PASS.

No production runtime code or service is changed by this subpart. Protected GitHub checks remain mandatory before merge.
