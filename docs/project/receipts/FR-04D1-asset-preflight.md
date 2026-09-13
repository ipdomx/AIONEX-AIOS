# FR-04D1 — Asset-root preflight before non-empty backup acceptance

Scope: add a metadata-only live preflight for protected platform asset roots before the FR-04D non-empty backup/restore acceptance.

Acceptance:
- The preflight covers all FR-04B asset roots already mounted in backup-worker.
- The preflight reports file counts, directory counts, payload bytes, and unsafe metadata counters without reading or hashing file contents.
- It fails closed on symlinks, special files, hard-linked files, unsafe ownership/permissions, or unreadable files.
- Cache, socket, model, Redis, and backup destination volumes remain outside the asset-root preflight.
- This segment does not enqueue a backup, run restore validation, delete artifacts, or change runtime services.
