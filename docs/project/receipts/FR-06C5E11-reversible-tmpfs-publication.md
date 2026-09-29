# FR-06C5E11 — preserved underlay and reversible tmpfs publication

## Scope and prerequisites

This source part follows merged PR #788 (`2cf91edffc6ffc175641365a23b0e46911f56842`). It introduces two journal-bound topology steps: `preserve_tmp_underlay` and `publish_tmpfs_mount`. It does not implement a production writer freezer, a production encrypted-swap attestor, systemd integration, reboot recovery, or full-host activation. FR-07 remains complete and FR-06 remains in progress.

The retained C5E10 staging journal must be finalized and its mount empty when preparing or advancing publication. The caller must supply an independent current authority callback binding the closed source/boot/maintenance context and writer-freeze, encrypted-swap, and underlay-reference evidence. A `FrozenEvidence` value or its digests are NOT proof of those conditions by themselves. There is no default production authority or activation CLI. C5E9 and its blocked source receipt are not imported, regenerated or replaced by this part.

## Implemented behavior

An operation-private bind reference preserves access to the ORIGINAL target directory before publication. The existing tmpfs is then moved, not copied or replaced by a new filesystem. The journal records and synchronizes an explicit intent before each native effect. The implementation checks the bound parent directories, locked staging journal, binding and lock identities, boot and mount namespace, exact tmpfs mount ID and root inode, source/options/geometry provenance, containing mount topology, and original recovery-reference root/device/inode. Stacked, nested, propagating, changed or aliased mounts are rejected.

Rollback reverses the move before releasing the underlay reference. It restores visibility of the original directory and returns the SAME tmpfs to private staging, including any files written after publication. It does not unmount, wipe, truncate, copy or implicitly delete the tmpfs. Returned nonempty staging is deliberately refused by C5E10's empty/readiness or teardown gates. Recovery of visibility is not a claim that new data was discarded or merged into the original directory.

The reference is removed only after the original directory is visible again, with ordinary `umount2(flags=0)`; busy references stay in place with an unresolved intent. There are no force/lazy-unmount or copy/delete fallbacks. A pending action is reconciled by observation, never replayed automatically. Every native step rechecks the independent callback. Advisory locks and markers do not prevent a privileged writer or cross-namespace ABA; externally enforced writer quiescence remains mandatory across final pathname resolution.

## Executed acceptance

- 58 focused tests, executed as `nobody`, cover real private journals/bindings with explicitly synthetic kernel and authority boundaries. They include unknown topology, replaced evidence/parents, namespace mismatch, additional original/tmpfs aliases, exact journal ordering, busy reference handling, source-staging changes after preparation, and interrupted effects in both directions.
- A separate QEMU/KVM guest with Linux 6.8.0-142 executed eleven native cases. Its REAL `/tmp` was covered and restored; original and newly created canary files retained their contents and inodes. An open underlay reference blocked removal. New data returned with the moved tmpfs and prevented staging teardown. Additional aliases of both the new filesystem and original underlay were independently rejected.
- Eight native guest child-process deaths exercised both steps before/after effects in both directions. Reopening retained pending intent, refused blind replay, and restored original visibility without data deletion.
- The guest uses one virtual CPU and 512 MiB RAM with no network, host filesystem shares or host block devices. The QEMU process is unprivileged with access to the existing KVM control device only. Frozen-writer/encrypted-swap/reference attestations in the guest are declared SYNTHETIC: native mount correctness is not production authorization or integrated encrypted-swap acceptance.

The complete Root suite, source hashes, quality checks, owned-VM cleanup and protected GitHub/main outcomes are recorded in immutable runtime manifests. Prior runs and diagnostics remain separate from final candidate acceptance; no source receipt itself claims deployment.

## Remaining gates

Production reference scans and writer freezes must be implemented/accepted independently, connected to real encrypted-swap evidence, and rechecked while admission is closed. Staging/publication still requires systemd/boot integration and composed rollback acceptance before a host window. C5D provider/resource drain, encrypted host-state transfer and C6 final acceptance remain open. An interrupted PROCESS is not a power-loss or host reboot test. Old underlay contents remain intact; secure erasure is not claimed.

Native API references: upstream Linux `mount(2)` bind/move semantics and `umount(2)` ordinary busy-mount semantics. This part uses only a single bind, single move or ordinary unmount per journal effect; it never applies host-wide mount changes.
