# FR-06C5E7 — journaled loop attachment with atomic operation provenance

## Scope

Source base: merged PR #785 at `1dda030b59b19a4f5c44e711864702ea9d9abff2`. This part implements `attach_swap_loop` and explicit reverse detachment. It does not implement encrypted mapper creation, random-key custody, encrypted swap activation, tmpfs/systemd transitions, a production context reader or an activation CLI. FR-07 stays complete; FR-06 stays in progress.

## Implementation

The adapter requires a published C5E6 backing whose original manifest, descriptor and accepted journal remain attached. It retains those locks and checks the original operation, closed context, boot and mount namespace. Preparation selects an explicitly named existing unused loop node; it does not allocate another node or adopt a pre-existing association.

`LOOP_CONFIGURE` sets the backing descriptor, exact capacity/offset/block size and an operation-specific marker in one Linux ioctl. There is no fallback to separate attach-and-label calls. The durable C5E2 intent precedes that ioctl. An interrupted operation reopens only when the kernel marker, backing device/inode, geometry, selected device and historical binding all agree. Reconciliation is observation-only and never repeats an uncertain effect.

Undo uses `LOOP_CLR_FD` only after two current observations find no dm holder, mounted filesystem or active swap on the loop. Other loop associations or a direct file-swap consumer on the backing are also rejected. A deferred autoclear or any changed/partial resource is not certified as detached. The adapter never deletes or truncates backing data. Generic journal ordering adds the new step before encrypted swap activation without reinterpreting an existing plan's per-plan event indexes.

Marker fields and advisory locks do not protect against an administrator able to rewrite kernel state. Independent operation-bound writer quiescence and production authority remain prerequisites. The descriptor/consumer checks are not an all-process fd/mmap inventory, a power-loss proof or a whole-host drain receipt.

## Allocation-accounting correction

The native mounted-filesystem test exposed a valid distinction: on the same fully allocated 16 MiB backing inode, extent metadata accounting changed from 32768 to 32776 blocks. The previous exact `st_blocks` comparison rejected this even with unchanged ownership, mode, links, capacity and inode. A separate regression reproduced the false rejection before correction.

`same_allocation` now compares the actual immutable file/security fields and independently requires both current and original observations to cover the entire capacity. Historical manifests retain their original observed block count and hash; they are not rewritten. Sparse allocation, replacement inode, ownership/permission/link/size drift and malformed metadata still fail. Payload integrity is not inferred from stat metadata. An earlier ext4 fixture with discard was correctly rejected for deallocating blocks; the final fixture uses `nodiscard` and asserts full allocation. Both earlier failures remain in runtime evidence.

## Acceptance

- 77 new directed cases; 211 combined loop/backing/transaction tests pass as `nobody`.
- Ruff passes for modified implementation/tests; Mypy passes for all three changed source modules with explicit namespace-package mapping.
- Nine cases pass on Linux 6.8.0-142 in a separate QEMU TCG guest: atomic tagged attachment and detachment; active encrypted-swap dm holder rejection; direct loop-swap rejection; a real mounted ext4 consumer rejection; rejection after a foreign marker is written on the same loop/backing; and four process-loss cases before/after apply/undo with explicit non-replaying recovery.
- The guest uses real `LOOP_CONFIGURE`, loop status and clear ioctls. Mapper/swap/filesystem creation is an explicit guest test fixture, not a shipped mapper adapter. The VM has no network, host shares or passed host devices and runs as `nobody` on the host. Only its private synthetic disk is writable.
- Native source/launch/console/results and the full source suite are retained separately under `docs/project/runtime/fr06c5e7-native-review-20260929T1125/`.

Parallel uncommitted source/test progress was observed in the original worktree; the reviewed source was copied with checksums to an independent worktree. Existing failed/successful evidence was retained without overwriting it. Final acceptance binds the reviewed source, not an earlier shortened guest suite.

## No production activation

No host loop, mapper, swap, mount, fstab, service, maintenance generation or provider was changed. Previously completed D10/D11/FR-07 work is not replayed. Previously blocked provider/combined verification/bootstrap actions were not repeated. Remaining work includes mapper/random-key ownership, composition with the rest of the system steps, independent production context and writer quiescence, C5D resource drain/host-state cutover, and C6 boot/recovery acceptance.

Linux UAPI reference: https://man7.org/linux/man-pages/man4/loop.4.html and the installed `/usr/include/linux/loop.h` used to verify LOOP_CONFIGURE=0x4C0A and the 304-byte loop_config layout.
