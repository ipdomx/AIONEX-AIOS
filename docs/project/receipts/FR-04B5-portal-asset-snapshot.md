# FR-04B5 — portal asset snapshot

Adds `portal_asset_data` only to the platform asset companion snapshot.

This segment intentionally excludes `realtime_recording_data`, `mobile_release_data`, `audio_song_ingress_data`, `security_source_data`, `security_remediation_data`, and all cache/socket volumes.

The backup worker receives the portal root read-only; the one-shot `backup-asset-root-init` is the only service in this segment that mounts it read-write for ownership/mode preparation.
