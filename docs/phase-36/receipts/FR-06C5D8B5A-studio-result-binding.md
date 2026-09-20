# FR-06C5D8B5A — Studio transactional output binding

Canonical receipt: `docs/project/receipts/FR-06C5D8B5A-studio-result-binding.md`.
The worker binds a successful business result to its exact acknowledged
publication before writing assets/revisions/results. Job, execution and
publication locks remain in the business transaction; cancellation or ambiguous
commit never authorizes a replay or file deletion. Forty-one real PostgreSQL /
worker / archive tests and static quality passed locally. Full acceptance and
merge are recorded in the canonical Project Hub only when observed.

This is not final resource settlement, post-crash cleanup, deployment, host drain
or final release. It adds no production migration or provider call.
