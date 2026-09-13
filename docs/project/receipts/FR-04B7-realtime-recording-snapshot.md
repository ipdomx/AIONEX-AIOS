# FR-04B7 — realtime recording snapshot

Scope: add `realtime_recording_data` only to platform backup snapshots.

Acceptance:
- `realtime_recording_data` is mounted read-only in `backup-worker`.
- `backup-asset-root-init` prepares `/var/lib/aionex/realtime-recordings` with owner `1001`, group `1000`, and explicit `chmod 2770` plus `CAP_FSETID` for LiveKit egress compatibility.
- Snapshot manifests include realtime_recording_data root totals and per-file hashes.
- Symlinks, non-regular files, world-readable paths, wrong ownership, and path traversal remain rejected.
- No audio ingress, security, cache, or socket roots are added in this segment.

Production defaults remain 1001:1000; tests may override the expected owner/group through Settings so CI does not require root-level chown.
