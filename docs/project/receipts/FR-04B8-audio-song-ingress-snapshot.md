# FR-04B8 — Audio song ingress backup snapshot

Scope: add `audio_song_ingress_data` only to platform backup snapshots.

Acceptance:
- `audio_song_ingress_data` is mounted read-only in `backup-worker`.
- `backup-asset-root-init` prepares `/var/lib/aionex/audio-song-provider-ingress` with private ownership and mode.
- `docker-entrypoint.sh` accepts a prepared read-only audio song ingress root and fails closed on unsafe ownership or permissions.
- Snapshot manifests include audio_song_ingress_data root totals and per-file hashes.
- Symlinks, non-regular files, unsafe permissions, and path traversal remain rejected.
- No security, cache, or socket roots are added in this segment.
