# FR-06C4B — isolated clean runtime-vault rehearsal

The rehearsal uses a disposable file-backed LUKS2 vault and synthetic runtime artifacts only. It never reads `/var/lib/docker` or `/var/lib/containerd` as input and never copies historical layers, snapshots, build cache or Docker JSON logs.

Acceptance requires wrong-key rejection, independent recovery-key open, active-key reopen, ext4 with `nodev,nosuid`, distinct `docker` and `containerd` subpaths, and absence of a synthetic plaintext marker from the closed raw image.

This remains source/lab only. C4C owns production provisioning and the guarded clean-runtime reconstruction path.
