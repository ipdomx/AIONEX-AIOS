# FR-06C5E4 — Read-only Linux memory-resource graph evidence

## Scope and parent acceptance

C5E1/C5E2 are merged in PRs #779/#780. Their combined main commit
`02fafcb1e8b80958cc211f7ffbb0fefae450d608` passed all five push workflows and was
synced to `/opt/AIOS` without changing services. C5E3 (#781) was merged after its
12 successful candidate checks at `9887bf2318c4440f17d9edc567cb2725bc0e409c`.
This part is based on that merged source. Main acceptance is checked separately;
no cancelled or pending workflow is counted as success.

This part ships only a read-only collector and strict evidence validator. It
DOES NOT ship `apply`, `undo`, a kernel mutation adapter or an activation CLI.
It does not import or execute the legacy `fr06c5_memory_controls.py` operator.
FR-07 remains complete. D10/D11 deployments are not repeated.

## Concrete checks

The reader joins independently pinned expectations across:

* the boot ID and current/init mount-namespace identities;
* the active swap set, matching block device numbers rather than aliases;
* dm name, UUID, size, read-only/suspended state, slaves and holders;
* cryptsetup's **status only** metadata: PLAIN / aes-xts-plain64 / 512-bit key
  size, reviewed sector size, zero offset, exact size and backing loop;
* LOOP_GET_STATUS64's backing device and inode, offset, size limit and flags;
* an open, pinned backing-file descriptor, checking the named path again
  without following symlink components;
* the exact visible `/tmp` mount ID, device, root, filesystem, mount options,
  capacity, propagation metadata and directory type/owner/mode.

Only the reviewed 4KiB page profile is accepted. One active encrypted swap is
required; duplicate aliases, additional swaps, plaintext/file swaps, stacked or
nested `/tmp` mounts, arbitrary loop offsets and extra consumers are rejected.
The backing must be singly linked, root:root, mode 0600, and exactly sized.

Two complete observations must agree, with a bounded 15-second collection
window. Used swap bytes are the only field excluded from topology equality;
the greater observed usage is retained. The separate memory-reserve predicate
includes all supplied active used swap pages. Neither predicate authorizes
swapoff or any other effect.

## Secret and command boundary

The collector never asks for a dm table, volume key, key file, backing-file
contents or a provider credential. Its only subprocess invocation is the fixed
`/usr/sbin/cryptsetup status aionex-fr06c5-swap` with C locale. Unknown status
fields fail with a generic error rather than returning raw output. The ioctl
buffer is cleared in a finally block, and only non-key loop identity fields
leave the decoder. Existing namespace handles are read; no namespace/mount or
loop device is created by this implementation or its tests.

## Negative controls and native checks

A fixture lacking the SWAPSPACE2 signature still fails the new graph check when
the crypt cipher is wrong: absence of a signature is not encryption proof.
Likewise a mapper name cannot compensate for the wrong backing inode, wrong
cipher/key size, extra active swap, wrong UUID, incorrect flags or a different
mount namespace.

Tests exercise the collector with explicit synthetic proc/sysfs/status/ioctl
inputs. They also pin actual disposable files, replace/unlink/rename them,
change their parents/link counts/metadata, and read the test process's real
mountinfo without changing a mount. Real encrypted swap or loop activation is
NOT tested here.

The first native mountinfo test exposed an overly restrictive parser: nsfs bind
mounts may have an opaque `net:[inode]` root instead of an absolute filesystem
path. This is now preserved only for nsfs, never normalized into a path and
never accepted as the `/tmp` root. The failed run is retained. The installed
cryptsetup binary's status format string was inspected without querying a
mapping; the sector-size field is a bare integer, not an invented `bytes`
suffix. The loop buffer follows the installed Linux UAPI layout (232 bytes).

## Acceptance and explicit limitations

Directed tests and the complete root suite are executed as `nobody` on owned
fixtures / a writable source snapshot. Counts and checksums are recorded in
`docs/project/runtime/fr06c5e4-kernel-observation-20260929/` and its LATEST pointer.
Ruff, Mypy and Project Hub validation are required before the source is accepted.

A consistent sample is NOT proof of creation by this operation, random key
quality/custody, writer quiescence, hidden-underlay drain, host boot, or power-loss
recovery. Two samples do not rule out ABA or a noncooperating administrator.
The result keeps all those authorization/closure claims false. Expected values
must not be auto-enrolled from the same untrusted observation and called owned.
A separate creation ledger, live closed-authority context, C5E1 underlay checks,
actual kernel effects and independently tested recovery are still required
before production activation. C5D/provider ambiguity and C6 remain open.

No blocked Replicate inventory, combined D10 postdeployment check or Telegram
bootstrap test is repeated in this part. No live swap, mapper, mount, systemd
unit, fstab, service or maintenance authority is changed.

## Primary format references

* Linux UAPI `include/uapi/linux/loop.h`, LOOP_GET_STATUS64 and loop_info64:
  https://github.com/torvalds/linux/blob/master/include/uapi/linux/loop.h
* Kernel dm-crypt target, cipher/offset/backing-device parameters:
  https://www.kernel.org/doc/html/latest/admin-guide/device-mapper/dm-crypt.html
* Linux mountinfo fields and per-namespace semantics:
  https://man7.org/linux/man-pages/man5/proc_pid_mountinfo.5.html
* cryptsetup status (metadata-only command):
  https://man7.org/linux/man-pages/man8/cryptsetup-status.8.html
