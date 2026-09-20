# FR-06C5D8A2B1 — Studio joined-thread source increment

Canonical receipt:
`docs/project/receipts/FR-06C5D8A2B1-studio-joined-threads.md`.

Archive build and storage now wait for their actual executor function despite
repeated caller cancellation. This does not settle durable ownership or prove
file cleanup, deployment or host drain. The one-shot guard still explicitly
keeps cleanup unverified. The separately blocked atomic-storage write was not
applied or retried. Existing storage publication and path-cleanup risks remain.

Local acceptance: 228 backend regression cases including 18 new actual-thread
and worker/PostgreSQL cases; 28 source contracts; Ruff and mypy 278. GitHub
checks, merge/main/source acceptance and QA cleanup are reported independently
in the canonical Project Hub when observed. FR-06 remains open.
