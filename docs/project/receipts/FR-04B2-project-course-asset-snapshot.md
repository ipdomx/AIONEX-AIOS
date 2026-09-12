# FR-04B2 — Project execution and course package backup coverage

Scope: small FR-04B slice only. This receipt covers adding two persistent roots to the protected companion snapshot used by platform backups:

- `project_execution_data` mounted read-only at `/var/lib/aionex/project-executions`.
- `course_package_data` mounted read-only at `/var/lib/aionex/course-packages`.

The change intentionally does not include media, studio, portal, mobile releases, realtime recordings, audio ingress, security source/remediation, Redis, caches, sockets, or model caches. Those remain separate FR-04 slices or FR-04C decisions.

The snapshot manifest is now `aionex-platform-asset-roots`, keeps per-file SHA-256/size, rejects symlinks and non-regular entries, and records per-root file counts and payload bytes. The existing `.three-d.tar` companion name and `three_d_snapshot` evidence key remain compatible for older restore evidence, but new evidence includes `roots` / `asset_snapshot_roots`.

Expected verification:

- root contract for this slice passes;
- backend test validates project/course files in the companion archive;
- Docker Compose production config renders with project/course read-only backup-worker mounts;
- no cache or unrelated asset root is added in this PR.
