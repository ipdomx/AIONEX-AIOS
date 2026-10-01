# FR-06C5E10 — private empty tmpfs staging, not production /tmp activation

## Scope

This independent source part starts from merge `26608e7081107ac6ed48f8cb81fd17f4b75e3d34` (PR #787). It does not import C5E9, recreate its blocked source receipt, publish its code, or claim its acceptance. C5E9 remains locally tested but unaccepted for publication. FR-07 remains complete; FR-06 is not complete.

The new `prepare_tmpfs_mount` step creates a tmpfs only at a newly prepared operation-private mountpoint. It does not cover `/tmp`, move any mount, edit fstab or systemd, migrate application data, or provide a production CLI. The new entry in the reviewed journal step order preserves all previous relative step ordering.

## Implemented behavior

A create-only binding records the original empty directory identity, private parent/bundle/lock, source commit, boot and maintenance operation/generation, mount namespace, bounded byte capacity, inode limit and memory reserve. The native mount uses a descriptor-relative path within the retained private bundle and an operation-specific source marker installed during creation. The native profile sets nodev/nosuid and a bounded tmpfs size and inode limit. The root mode is 1777 inside a 0700 operation ancestor; this is not a public /tmp path.

The adapter checks the current and init mount namespaces, containing mount propagation, exact target/source/device, mode, capacity and inode limit. Stacked or nested mounts, foreign sources, other bind aliases of the same filesystem, drifted metadata and unknown observations are rejected. Memory reserve is rechecked before creation. Final staging acceptance also requires no directory entries, extended attributes or allocated data blocks; a structure-only match does not certify an empty stage.

Every native action follows a durable journal intent. A failed or interrupted action stays pending; observation-only reconciliation never creates a replacement mount or repeats the effect. Undo preserves a nonempty mount rather than deleting its contents. It uses exactly one `umount2` with flags zero, without forced or lazy detachment, retry loops, or recursive deletion. The kernel's busy-reference rejection is retained as an uncertain intent. Explicit recovery may proceed only after the actual consumer has been removed and the same operation reconciled. Success requires the original empty directory identity to be visible again.

## Tests already executed

- 68 directed pytest cases as `nobody`, including real private files and journals, initial and final emptiness, allocation limits, current reserve, boot/namespace changes, replaced bindings/paths/locks, unknown or aliased mounts, nonempty/busy retention, explicit recovery and native syscall argument contracts. Kernel changes in pytest are explicit doubles.
- Eight native cases in a dedicated offline QEMU/KVM guest on Linux 6.8.0-142: actual private tmpfs creation/removal; configured capacity and inode limits; nonempty canary preservation; busy directory-FD rejection; bind-alias rejection; and four process-loss cases before/after mount/unmount with no blind replay. The original directory inode was restored. The guest's `/tmp` was not changed.
- The first VM run failed because an oversized proc/sysctl read returned ENOMEM. The reader was changed to bounded 4 KiB requests, with independent overall-size and complete-data checks; the failed log is retained. A review also reproduced three false empty-stage certifications (entries, attributes, allocated blocks); the final implementation refuses all three.
- Complete source suite, immutable native input hashes, quality checks and GitHub acceptance are retained separately in the runtime acceptance manifest. Source-local tests are not deployment evidence.

## Remaining independent gates

Tmpfs can use swap; this part does not attest encrypted swap or provide a non-swappable application store. It never populates application data. Publishing a mount to `/tmp` still requires accepted encrypted-memory conditions, original-underlay preservation, independently frozen writers, complete process/namespace coverage, composed recovery and real boot integration. Markers and advisory locks do not protect against a privileged actor or ABA replacement. This step is not a general mount manager or an operation across reboots.

No host mount, swap, mapper, service, maintenance authority or provider was changed. Native mutations occurred only in the separately booted guest. No host power-loss/reboot, full-host drain, C5D cutover, C6 encryption closure or final release is claimed.
