# FR-04B7 Receipt — Realtime recording snapshot

Date: 2026-09-13
Scope: add `realtime_recording_data` only to the protected platform asset companion snapshot.

Realtime recordings intentionally use a group-private policy for LiveKit egress compatibility: directories are `2770` and files are `0660` under owner `1001` and group `1000`. This segment keeps audio ingress, security roots, cache volumes, and socket volumes outside the change.

Production defaults remain 1001:1000; tests may override the expected owner/group through Settings so CI does not require root-level chown.
