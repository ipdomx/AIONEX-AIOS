# FR-06C5E5 — journal-bound native legacy-swap step and independent-kernel acceptance

## Scope and boundaries

Base: merged C5E4 `ed4096d47e66feff3e120ae21ef9494925ea8e31`.

This implements **one native kernel step**, `disable_legacy_swap`, with its explicit
inverse, through `LegacySwapAdapter` and the C5E2 durable intent journal. It does
not activate memory controls on the production host. A production context reader,
all-step composition, backing/mapper creation ownership, systemd activation, live
writer quiescence, C5D drain/cutover and C6 acceptance remain separate work.

The adapter accepts a single-step journal intentionally: final-state checks for
coexisting replacement encrypted swap are not silently broadened. There is no
production CLI, host-wide swap command, formatting of the old swap header, copy
of live swap contents, automatic replay or implicit rollback.

## Actual implementation

- Pins the file descriptor and parent/metadata identity without reading swap
  contents. The native libc `swapoff` and `swapon` calls operate on that same
  `/proc/self/fd/N`; a newly substituted path cannot become their target.
- Matches `/proc/swaps` to the pinned inode. Rejects extra active swaps, block
  devices in place of the original file, changes in file/parent/binding/lock,
  uninspectable evidence, different boot/init mount namespace, unsupported page
  geometry, and priorities that cannot be reproduced.
- Preserves automatic priority -2 or the exact explicit priority. No discard,
  header rewrite or destructive reinitialization is used during restoration.
- Rechecks available memory against current used swap plus the explicit reserve
  immediately before swapoff. This is observation under the caller's frozen
  writer contract, not a kernel reservation or protection against a hostile root.
- Requires an attached matching journal and a durable direction-specific intent
  before a kernel effect. Nonzero errno, a return without the expected kernel
  state, context drift or interrupted completion retain the uncertain intent.
- Recovery opens the same binding, observes without repeating the effect, halts
  interrupted forward execution, and verifies the original active state before
  recording restoration. An advisory state-directory lock serializes cooperating
  controllers, not arbitrary external administrative changes.

## Tests actually performed

### Nonroot suite

67 directed tests exercise actual private files and journals with explicit fake
kernel effects. They never call native swap syscalls on the server. Coverage
includes syscall flags/errno, all identity boundaries, low-memory refusal, durable
intent ordering, partial writes, forward expiry, replay refusal and both recovery
directions. Ruff and Mypy are checked without rule suppression.

A complete-root-suite result is retained alongside this receipt in the runtime
acceptance manifest; directed tests are included in that total, not additive.

### Separate Linux kernel in QEMU (not a container)

QEMU 8.2.2 tools were downloaded/extracted into an owned lab directory, without
installing host packages. The emulator ran as UID 65534 under TCG, one virtual
CPU and 512 MiB RAM, with **no network, shared host filesystem, host block device,
KVM passthrough or production configuration**. It booted an independently running
Linux `6.8.0-142-generic` kernel with an owned ephemeral virtual ext4 disk.

The committed inert fixture is `tests/fixtures/fr06c5e/legacy_swap_guest.py.txt`.
Its entry guard requires the dedicated virtual DMI identity and `/dev/vda` mount.
It is not a pytest test and is never executed by the normal host suite.

The accepted VM run demonstrated:

1. Actual swapoff of a 64 MiB synthetic file while **8,437,760 bytes** were in
   swap after guest-only `MADV_COLD`/`MADV_PAGEOUT`. The anonymous canary remained
   byte-for-byte identical. Explicit rollback reactivated the same original file
   inode, without formatting it.
2. Four real SIGKILL interruptions of guest child controllers: before/after the
   apply syscall and before/after the undo syscall. Journal reopen retained the
   pending intent, prohibited blind replay, and verified restoration.
3. A real loop device, native `dm-crypt` PLAIN AES-XTS-512 mapping, active encrypted
   swap and a real tmpfs `/tmp`. The unchanged C5E4 Linux reader accepted two
   native graph samples, including the actual `LOOP_GET_STATUS64` ioctl. The
   synthetic random key was passed over stdin, not written into a key file.
4. The guest disabled its swap, closed its mapper, detached its loop and unmounted
   its tmpfs before powering down. This is guest cleanup, not a host drain proof.

No production swapoff, swapon, mount, systemctl, application/provider inventory,
blocked D10 verification, blocked Telegram bootstrap or blocked Replicate request
was executed. Guest process loss is not power-loss, production-reboot or durable
random-key-custody acceptance. C5E4 correctly continues to report those unproved
properties as false even when the native kernel graph matches.

## Retained failures and limitations

- The first nonroot reader unit test lacked a synthetic PID1 namespace field;
  access was correctly denied. Only the unit fixture was corrected, not the
  native namespace guard.
- The first privately extracted QEMU invocation could not locate its TCG module;
  it failed before any VM boot. Its log is retained. The explicit module search
  path was corrected without a host package installation.
- The first successful VM run had zero used swap and proved only an empty swap
  transition. It was not promoted to page-reclamation evidence. The subsequent
  run required positive measured swap use before proceeding.

## Continuity

Runtime evidence: `docs/project/runtime/fr06c5e5-kernel-steps-20260929/`.

C5E4 is merged; post-merge acceptance and source synchronization are independently
recorded. C5E5 is a new candidate until its own checks/merge complete. No server
memory activation is implied by source merge. FR-07 remains complete. FR-06 and
the final release remain open pending all remaining operational requirements.
