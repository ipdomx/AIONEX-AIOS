# FR-06C5D8A1 — Studio request-admission reporting reference

The single acceptance receipt for this bounded change is
`docs/project/receipts/FR-06C5D8A1-studio-request-admission.md`.
This entry satisfies the existing Phase 36 product-path reporting contract; it
is a pointer, not a second roadmap or runtime status source.

The change guards Studio job request/retry admission with schema 7 and migration
0054. Local acceptance includes 200 backend regressions, 14 source contracts,
full Ruff and application mypy. Full repository CI and protected merge remain
unconfirmed at candidate creation. Worker ownership/cleanup, production
migration/deployment, host drain and FR-06 completion are not claimed.
