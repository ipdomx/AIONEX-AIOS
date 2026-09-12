# Phase 36N / FR-04B2 Receipt — Project and course asset backup roots

This is a source receipt for the FR-04B small slice that adds only `project_execution_data` and `course_package_data` to protected platform backup companion snapshots. It preserves the existing database backup flow, the existing 3D snapshot evidence compatibility key, and the strict rejection of symlinks/non-regular files. Runtime deployment and restore evidence must be recorded separately after protected checks and rollout.

A follow-up fix in the same PR adds a root initializer so CI-created Docker volumes meet the existing private-root contract before backup-worker healthchecks run. This does not relax the backup gate.
