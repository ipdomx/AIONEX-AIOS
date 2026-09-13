# FR-04D1A — Align asset preflight with snapshot metadata policy

Scope: fix the FR-04D1 preflight so it mirrors `ThreeDAssetSnapshotExecutor` metadata rules.

Acceptance:
- Default asset roots enforce directory/file modes but do not require a fixed owner/gid.
- Realtime recordings still enforce owner `1001`, group `1000`, directory mode `2770`, and file mode `0660`.
- The live preflight can be rerun without reading file contents or hashing user data.
- No backup enqueue, restore validation, deletion, Compose change, or runtime service rollout is performed in this segment.
