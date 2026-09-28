# FR-06C5E1 — Read-only memory preflight and offline enabled boot graph

Base main: `c8b3b7247e6c0801f9432b71c6ef3641bad694c1` (PR778 deployed separately).
Prepared C5E source retained: `13b76558f585f432acc831b6ad0448ee5909b5bd`.
FR-07 remains complete. FR-06, C5D host-state migration, C5E activation and C6
are NOT closed by this receipt.

## Scope of this source part

This part deliberately imports no unsafe historical apply/rollback or boot
activation command into main. It provides two inert components that can be
integrated into the repaired memory operator only after the remaining safety
review. Source merge neither changes swap nor mounts /tmp, edits fstab, installs
a unit, stops a process, reads a key, or changes application admission.

`scripts/security/fr06c5_memory_preflight.py` preserves the prepared branch's
block-device identity rule. A mapper and /dev/dm-N alias match by st_rdev only
when both are block devices. Inaccessible identities are UNKNOWN. Strict swap
inventory parsing rejects inconsistent, duplicate and malformed rows; matching
an alias explicitly does not attest the cryptographic mapping or its backing.

The tmp underlay reader opens path components without following symlinks and
pins a directory descriptor. It inventories inode metadata, not payload bytes,
and uses that same pin even when the visible directory name is replaced. It
includes each observed thread's descriptors, cwd, root and file-backed memory
mappings, matching hard-link aliases by device/inode. The scanner does not drop
unlinked same-filesystem provenance ambiguity or skip inaccessible references.
Changing inode inventories, process identity, thread/process populations, missing
observations and inventory bounds prevent a clear result. The exact scanner-owned
read-only pin is the only descriptor exemption; no worker is exempted.

Reports distinguish observed_clear from references_present and unknown, record
actual measured counts, and never set activation_authorized or full_host_closure.
A selected-process laboratory observation is explicitly not host coverage.
A pinned directory and a snapshot do NOT quiesce concurrent writers; a separate
operation-owned maintenance/freeze boundary remains mandatory. A post-cover scan
must retain the original pin, rather than inventorying the new visible tmpfs.

## Enabled boot graph, not only unit syntax

`scripts/security/fr06c5_memory_boot_plan.py` renders a proposal as data only.
The prepared unit ordered encrypted swap after local-fs.target while tmpfs /tmp
is ordered after swap.target: the enabled graph contains a cycle. The proposal
requires the specific executable/code/backing/state filesystem mounts instead
of the aggregate local-fs.target and makes /tmp depend on successful encrypted
swap startup. No native unit file is installed by this part.

Actual `systemd-analyze --root=<owned scratch root> --generators=no --man=no verify
 default.target` reproduced the cycle with enabled .wants links. Importantly,
the verifier returned exit code ZERO while reporting that it removed the swap
service's job to break the cycle. The first two negative test expectations
incorrectly assumed a nonzero exit status; that failed run is preserved. The
corrected acceptance predicate rejects ANY diagnostics as well as nonzero status;
it does not weaken the verifier or ignore its output.

The corrected graph passes the real verifier both with a single root filesystem
and separate /usr, /var and /opt mounts. A tmpfs /var backing dependency is
correctly rejected as cyclic. These are controlled offline graph configurations,
not the actual host's enabled graph, nor an actual boot, swap setup or mapper test.
Fixture executable metadata is never executed.

## Executed acceptance

68 directed tests passed under the unprivileged `nobody` account:

- 59 read-only preflight cases, including an actual Linux mmap process;
- 9 boot-plan/acceptance cases using the real systemd dependency verifier.

The real mmap regression creates one exclusively owned /tmp directory and child
process. The child opens and maps its own file through libc, closes the file
descriptor, and keeps a writable shared mapping alive. The exact retained
fd-only scanner returns no holder; the new reader finds the mapping. Only after
the child explicitly unmaps does the new measured reference count become zero.
The child exits normally and its own fixture directory is removed. No production
process was scanned, signalled or stopped for this proof.

Directory pin survival is tested with real directory rename/replacement and
synthetic /proc data. Permission errors, missing references, PID reuse, nonleader
thread mappings, file changes, hard-link aliases, unlinked provenance and malformed
swap/maps data are covered. No live swap, cryptsetup, mount, fstab, service or
provider operation was executed in these tests.

Canonical evidence: `docs/project/runtime/fr06c5e-memory-preflight-20260928/`.
The root-suite and protected exact-commit results are recorded there separately;
directed counts are overlapping, not added to root coverage.

## Remaining blockers retained, not solved by a reader

The old `fr06c5_memory_controls.py` remains on the prepared branch, not in main.
Its durable intent/phase journal, idempotent reconciliation, ownership-aware and
measured rollback, partial mapper creation recovery, actual enabled host graph,
post-cover underlay inspection inside a proven writer freeze, memory reserve,
encrypted mapper/backing attestation and real activation/boot/recovery acceptance
still require completion. Do not run that historical apply/rollback because this
preflight passed. C5D must still meet its host-state cutover requirements and
ambiguous provider work remains unresolved. No blocked Replicate inventory,
post-D10 combined probe or Telegram token/bootstrap test was retried.

## Primary technical references

- Linux kernel tmpfs documentation: `https://docs.kernel.org/filesystems/tmpfs.html`.
  tmpfs may use swap; placing /tmp on tmpfs alone is not an encrypted-swap proof.
- Linux man-pages proc_pid_maps(5):
  `https://man7.org/linux/man-pages/man5/proc_pid_maps.5.html`.
- systemd mount dependencies:
  `https://www.freedesktop.org/software/systemd/man/systemd.mount.html`.
  The repository's runtime evidence retains actual offline verifier results,
  rather than inferring success from these documents.
